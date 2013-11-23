import json
import cPickle
from django.utils.timezone import utc
import mapnik
from collections import OrderedDict
from hashlib import md5
from ga_resources import models as m
import os
from django.conf import settings as s
import sh
from datetime import datetime
from urllib2 import urlopen
import requests
import re
from django.conf import settings
from ga_resources import predicates
from ga_resources.models import SpatialMetadata
import time
import math

from osgeo import osr

VECTOR = False
RASTER = True

class Driver(object):
    """Abstract class that defines a number of reusable methods to load geographic data and create services from it"""
    def __init__(self, data_resource):
        self.resource = data_resource
        self.cache_path = self.resource.cache_path
        self.cached_basename = os.path.join(self.cache_path, os.path.split(self.resource.slug)[-1])

    def ensure_local_file(self, freshen=False):
        if self.resource.resource_file:
            _, ext = os.path.splitext(self.resource.resource_file.name)
        elif self.resource.resource_url:
            _, ext = os.path.splitext(self.resource.resource_url)
        else:
            return None

        cached_filename = self.cached_basename + ext
        self.src_ext = ext

        ready = os.path.exists(cached_filename) and not freshen

        if not ready:
            if self.resource.resource_file:
                if os.path.exists(cached_filename):
                    os.unlink(cached_filename)
                try:
                    os.symlink(os.path.join(s.MEDIA_ROOT, self.resource.resource_file.name), cached_filename)
                except:
                    pass
            elif self.resource.resource_url:
                if self.resource.resource_url.startswith('ftp'):
                    result = urlopen(self.resource.resource_url).read()
                    if result:
                        with open(cached_filename, 'wb') as resource_file:
                            resource_file.write(result)
                else:
                    result = requests.get(self.resource.resource_url)
                    if result.ok:
                        with open(cached_filename, 'wb') as resource_file:
                            resource_file.write(result.content)
            return True
        else:
            return False

    @classmethod
    def supports_mutiple_layers(cls):
        return True

    @classmethod
    def supports_download(cls):
        return True

    @classmethod
    def supports_related(cls):
        return True

    @classmethod
    def supports_upload(cls):
        return True

    @classmethod
    def supports_configuration(cls):
        return True

    @classmethod
    def supports_point_query(cls):
        return True

    @classmethod
    def supports_save(cls):
        return True

    @classmethod
    def datatype(cls):
        return VECTOR

    def filestream(self):
        self.ensure_local_file()
        return open(self.cached_basename + self.src_ext)

    def mimetype(self):
        return "application/octet-stream"

    def ready_data_resource(self, **kwargs):
        """Other keyword args get passed in as a matter of course, like BBOX, time, and elevation, but this basic driver
        ignores them"""

        changed = self.resource.spatial_metadata and self.ensure_local_file(
            freshen='fresh' in kwargs and kwargs['fresh'])
        if changed:
            self.compute_fields(**kwargs)

        return self.resource.slug, self.resource.srs

    def compute_fields(self, **kwargs):
        if self.ensure_local_file() is not None:
            filehash = md5()
            with open(self.cached_basename + self.src_ext) as f:
                b = f.read(10 * 1024768)
                while b:
                    filehash.update(b)
                    b = f.read(10 * 1024768)

            md5sum = filehash.hexdigest()
            if md5sum != self.resource.md5sum:
                self.resource.md5sum = md5sum
                self.resource.last_change = datetime.utcnow().replace(tzinfo=utc)

        if not self.resource.spatial_metadata:
            self.resource.spatial_metadata = SpatialMetadata.objects.create()


    def get_metadata(self, **kwargs):
        """If there is metadata conforming to some standard, then return it here"""
        return {}

    def get_data_fields(self, **kwargs):
        """If this is a shapefile, return the names of the fields in the DBF and their datattypes.  If this is a data
        raster (as opposed to an RGB or grayscale raster, return the names of the bands or subdatasets and their
        datatypes."""
        return []

    def get_filename(self, xtn):
        filename = os.path.split(self.resource.slug)[-1]
        return os.path.join(self.cache_path, filename + '.' + xtn)

    def get_data_for_point(self, wherex, wherey, srs, fuzziness=30, **kwargs):
        _, nativesrs, result = self.ready_data_resource(**kwargs)

        s_srs = osr.SpatialReference()
        t_srs = nativesrs

        if srs.lower().startswith('epsg'):
            s_srs.ImportFromEPSG(int(srs.split(':')[-1]))
        else:
            s_srs.ImportFromProj4(srs.encode('ascii'))

        crx = osr.CoordinateTransformation(s_srs, t_srs)
        x1, y1, _ = crx.TransformPoint(wherex, wherey)
        
        # transform wherex and wherey to 3857 and then add $fuzziness meters to them
        # transform the fuzzy coords to $nativesrs
        # substract fuzzy coords from x1 and y1 to get the fuzziness needed in the native coordinate space
        epsilon = 0
        if fuzziness > 0:
           meters = osr.SpatialReference()
           meters.ImportFromEPSG(3857) # use web mercator for meters
           nat2met = osr.CoordinateTransformation(s_srs, meters) # switch from the input srs to the metric one
           met2nat = osr.CoordinateTransformation(meters, t_srs) # switch from the metric srs to the native one
           mx, my, _ = nat2met.TransformPoint(wherex, wherey) # calculate the input coordinates in meters
           fx = mx+fuzziness # add metric fuzziness to the x coordinate only to get a radius
           fy = my 
           fx, fy, _ = met2nat.TransformPoint(fx, fy)
           epsilon = fx - x1 # the geometry should be buffered by this much
        elif 'bbox' in kwargs and 'width' in kwargs and 'height' in kwargs:
           # use the bounding box to calculate a radius of 8 pixels around the input point
           minx, miny, maxx, maxy = kwargs['bbox']
           width = int(kwargs['width']) # the tile width in pixels
           height = int(kwargs['height']) # the tile height in pixels
           dy = (maxy-miny)/height # the height delta in native coordinate units between pixels
           dx = (maxx-minx)/width # the width delta in native coordinate units between pixels
           x2, y2, _ = crx.TransformPoint(wherex+dx*8, wherey) # return a point 8 pixels to the right of the source point in native coordinate units
           epsilon = x2 - x1 # the geometry should be buffered by this much
           
           
        else:
           print json.dumps(kwargs, indent=4)

        return result, x1, y1, epsilon

    def as_dataframe(self, **kwargs):
        raise NotImplementedError("This driver does not support dataframes")

    def summary(self, **kwargs):

        sum_path = self.get_filename('sum')
        if self.resource.big and os.path.exists(sum_path):
            with open(sum_path) as sm:
                return cPickle.load(sm)

        df = self.as_dataframe(**kwargs)
        keys = [k for k in df.keys() if k != 'geometry']
        type_table = {
            'float64': 'number',
            'int64': 'number',
            'object': 'text'
        }

        ctx = [{'name': k} for k in keys]
        for i, k in enumerate(keys):
            s = df[k]
            ctx[i]['kind'] = type_table[s.dtype.name]
            ctx[i]['tags'] = [tag for tag in [
                'unique' if predicates.unique(s) else None,
                'not null' if predicates.not_null(s) else None,
                'null' if predicates.some_null(s) else None,
                'empty' if predicates.all_null(s) else None,
                'categorical' if predicates.categorical(s) else None,
                'open ended' if predicates.continuous(s) else None,
                'mostly null' if predicates.mostly_null(s) else None,
                'uniform' if predicates.uniform(s) else None
            ] if tag]
            if 'categorical' in ctx[i]['tags']:
                ctx[i]['uniques'] = [x for x in s.unique()]
            for k, v in s.describe().to_dict().items():
                ctx[i][k] = v

        if self.resource.big:
            with open(sum_path, 'w') as sm:
                cPickle.dump(ctx, sm)

        return ctx

def deg2num(lat_deg, lon_deg, zoom):
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0 * n)
    return (xtile, ytile)


def num2deg(xtile, ytile, zoom):
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    lat_deg = math.degrees(lat_rad)
    return (lat_deg, lon_deg)


def compile_layer(rl, layer_id, srs, css_classes, **parameters):
    return {
        "id" : parameters['id'] if 'id' in parameters else re.sub('/', '_', layer_id),
        "name" : parameters['name'] if 'name' in parameters else re.sub('/', '_', layer_id),
        "class" : ' '.join(rl.default_class if 'default' else cls for cls in css_classes).strip(),
        "srs" : srs if isinstance(srs, basestring) else srs.ExportToProj4(),
        "Datasource" : parameters
    }

def compile_mml(srs, styles, *layers):
    stylesheets = [m.Style.objects.get(slug=s.split('.')[0]) for s in styles]
    css_classes = set([s.split('.')[1] if '.' in s else 'default' for s in styles])

    mml = {
        'srs' : srs,
        'Stylesheet' : [{ "id" : re.sub('/', '_', stylesheet.slug), "data" : stylesheet.stylesheet} for stylesheet in stylesheets],
        'Layer' : [compile_layer(rl, layer_id, lsrs, css_classes, **parms) for rl, (layer_id, lsrs, parms) in layers]
    }
    return mml


def compile_mapfile(name, srs, stylesheets, *layers):
    with open(name + ".mml", 'w') as mapfile:
        mapfile.write(json.dumps(compile_mml(srs, stylesheets, *layers), indent=4))
    carto = sh.Command(settings.CARTO_HOME + "/bin/carto")
    carto(name + '.mml', _out=name + '.xml')


def prepare_wms(layers, srs, styles, bgcolor=None, transparent=None, **kwargs):
    d = OrderedDict(layers=layers, srs=srs, styles=styles, bgcolor=bgcolor, transparent=transparent)
    shortname = md5()
    for key, value in d.items():
        shortname.update(key)
        shortname.update(unicode(value))
    cache_entry_basename = shortname.hexdigest()
    cache_path = os.path.join(s.MEDIA_ROOT, '.cache', '_cached_layers')
    if not os.path.exists(cache_path):
        os.makedirs(cache_path)  # just in case it's not there yet.

    # add the prefix into the Redis database to make sure we know how to clean the cache out if the resource is modified
    cached_filename = os.path.join(cache_path, cache_entry_basename)
    for style in styles:
        s.WMS_CACHE_DB.sadd(style, cached_filename)
    for layer in layers:
        s.WMS_CACHE_DB.sadd(layer, cached_filename)

    layer_specs = []
    for layer in layers:
        if "#" in layer:
            layer, kwargs['sublayer'] = layer.split("#") 
        rendered_layer = m.RenderedLayer.objects.get(slug=layer)
        driver = rendered_layer.data_resource.driver_instance
        layer_spec = driver.ready_data_resource(**kwargs)
        layer_specs.append((rendered_layer, layer_spec))

    if not os.path.exists(cached_filename + ".xml"):  # not an else as previous clause may remove file.
        try:
            with open(cached_filename + ".lock", 'w') as w:
                 compile_mapfile(cached_filename, srs, styles, *layer_specs)
            os.unlink(cached_filename + ".lock")
        except sh.ErrorReturnCode_1, e:
            raise RuntimeError(str(e.stderr))
        except:
            pass

    return cached_filename


def render(fmt, width, height, bbox, srs, styles, layers, **kwargs):
    if srs.lower().startswith('epsg'):
        if srs.endswith("900913") or srs.endswith("3857"):
            srs = "+proj=merc +a=6378137 +b=6378137 +lat_ts=0.0 +lon_0=0.0 +x_0=0.0 +y_0=0 +k=1.0 +units=m +nadgrids=@null"
        else:
            srs = "+init=" + srs.lower()

    name = prepare_wms(layers, srs, styles, **kwargs)
    filename = md5()

    filename.update("{bbox}.{width}x{height}".format(
        name=name,
        bbox=','.join(str(b) for b in bbox),
        width=width,
        height=height,
        fmt=fmt
    ))
    filename = name + filename.hexdigest() + '.' + fmt

    if os.path.exists(filename):
        return filename
    else:
        while os.path.exists(name + ".lock"):
            time.sleep(0.05)
        m = mapnik.Map(width, height)
        mapnik.load_map(m, name + '.xml')
        m.zoom_to_box(mapnik.Box2d(*bbox))
        mapnik.render_to_file(m, filename, fmt)

    return filename


from sqlite3 import dbapi2 as db

class MBTileCache(object):
    def __init__(self, layers, styles, **kwargs):
        self.srs = "+proj=merc +a=6378137 +b=6378137 +lat_ts=0.0 +lon_0=0.0 +x_0=0.0 +y_0=0 +k=1.0 +units=m +nadgrids=@null"
        self.name = prepare_wms(layers, self.srs, styles, **kwargs)
        self.cachename = self.name + '.mbtiles'

        self.layers = layers
        self.styles = styles
        self.kwargs = kwargs

        if os.path.exists(self.cachename):
            conn = db.connect(self.cachename)
        else:
            conn = db.connect(self.cachename)
            cursor = conn.cursor()
            cursor.executescript("""
                    BEGIN TRANSACTION;
                    CREATE TABLE android_metadata (locale text);
                    CREATE TABLE grid_key (grid_id TEXT,key_name TEXT);
                    CREATE TABLE grid_utfgrid (grid_id TEXT,grid_utfgrid BLOB);
                    CREATE TABLE keymap (key_name TEXT,key_json TEXT);
                    CREATE TABLE images (tile_data blob,tile_id text);
                    CREATE TABLE map (zoom_level INTEGER,tile_column INTEGER,tile_row INTEGER,tile_id TEXT,grid_id TEXT);
                    CREATE TABLE metadata (name text,value text);
                    CREATE VIEW tiles AS SELECT map.zoom_level AS zoom_level,map.tile_column AS tile_column,map.tile_row AS tile_row,images.tile_data AS tile_data FROM map JOIN images ON images.tile_id = map.tile_id ORDER BY zoom_level,tile_column,tile_row;
                    CREATE VIEW grids AS SELECT map.zoom_level AS zoom_level,map.tile_column AS tile_column,map.tile_row AS tile_row,grid_utfgrid.grid_utfgrid AS grid FROM map JOIN grid_utfgrid ON grid_utfgrid.grid_id = map.grid_id;
                    CREATE VIEW grid_data AS SELECT map.zoom_level AS zoom_level,map.tile_column AS tile_column,map.tile_row AS tile_row,keymap.key_name AS key_name,keymap.key_json AS key_json FROM map JOIN grid_key ON map.grid_id = grid_key.grid_id JOIN keymap ON grid_key.key_name = keymap.key_name;
                    CREATE UNIQUE INDEX grid_key_lookup ON grid_key (grid_id,key_name);
                    CREATE UNIQUE INDEX grid_utfgrid_lookup ON grid_utfgrid (grid_id);
                    CREATE UNIQUE INDEX keymap_lookup ON keymap (key_name);
                    CREATE UNIQUE INDEX images_id ON images (tile_id);
                    CREATE UNIQUE INDEX map_index ON map (zoom_level, tile_column, tile_row);
                    CREATE UNIQUE INDEX name ON metadata (name);
                    END TRANSACTION;
                    ANALYZE;
                    VACUUM;
               """)

        self.cache = conn

    def fetch_tile(self, z, x, y):
        tile_id = ','.join((z,x,y))
        sw = num2deg(x, y+1, z)
        ne = num2deg(x+1, y, z)
        width = 256
        height = 256
        insert_map = """INSERT OR REPLACE INTO map (tile_id,zoom_level,tile_column,tile_row,grid_id) VALUES(?,?,?,'');"""
        insert_data = """INSERT OR REPLACE INTO images (tile_id,tile_data) VALUES(?,?);"""

        with self.cache.cursor() as c:
            c.execute("SELECT tile_data FROM images WHERE tile_id=?", tile_id)
            try:
                blob = c.fetchone()[0]
            except:
                tile_id = filename = render('png', width, height, (sw[0], sw[1], ne[0], ne[1]), self.srs, self.styles, self.layers, **self.kwargs)
                with open(filename) as f:
                    blob = f.read()
                os.unlink(filename)
                with self.cache.cursor() as d:
                    d.execute(insert_map, tile_id, z, x, y)
                    d.execute(insert_data, tile_id, blob)
        return blob

    def seed_tiles(self, min_zoom, max_zoom):
        for z in range(min_zoom, max_zoom+1):
            for x in range(0, 2**z):
                for y in range(0, 2**z):
                    self.fetch_tile(z, x, y)

