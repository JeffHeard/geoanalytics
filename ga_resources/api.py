from tastypie.api import Api
from tastypie.resources import ModelResource
from tastypie.authentication import ApiKeyAuthentication
from tastypie.authorization import Authorization

from ga_resources import models
from ga_irods import models as irods
from django.contrib.auth import models as auth


class AbstractPageResource(ModelResource):
    """Abstract class that provides sensible defaults for creating new pages via the RESTful API. e.g. unless there's
     some specific value passed in for whether or not the page should show up in the header, footer, and sidebar, we
     want to dehydrate that field specifically"""

    def _dehydrate_with_default(self, bundle, datum, default):
        if datum not in bundle.data or bundle.data[datum] is None:
            return default

    def dehydrate_in_menus(self, bundle):
        return self._dehydrate_with_default(bundle, 'in_menus', False)

    def dehydrate_requires_login(self, bundle):
        return self._dehydrate_with_default(bundle, 'requires_login', False)

    def dehydrate_in_sitemap(self, bundle):
        return self._dehydrate_with_default(bundle, 'in_sitemap', False)


class BaseMeta(object):
    allowed_methods = ['get', 'put', 'post', 'delete']
    authorization = Authorization()
    authentication = ApiKeyAuthentication()


class Group(ModelResource):
    class Meta:
        authorization = Authorization()
        authentication = ApiKeyAuthentication()
        allowed_methods = ['get']
        queryset = auth.Group.objects.all()
        resource_name = "group"


class User(ModelResource):
    class Meta:
        authorization = Authorization()
        authentication = ApiKeyAuthentication()
        allowed_methods = ['get']
        queryset = auth.User.objects.all()
        resource_name = "user"


class RodsEnvironment(ModelResource):
    class Meta:
        authorization = Authorization()
        authentication = ApiKeyAuthentication()
        allowed_methods = ['get']
        queryset = irods.RodsEnvironment.objects.all()
        resource_name = "irods_environment"


class AncillaryResource(AbstractPageResource):
    class Meta(BaseMeta):
        queryset = models.AncillaryResource.objects.all()
        resource_name = "ancillary"


class DataResource(AbstractPageResource):
    class Meta(BaseMeta):
        queryset = models.DataResource.objects.all()
        resource_name = 'data'


class ResourceGroup(AbstractPageResource):
    class Meta(BaseMeta):
        queryset = models.ResourceGroup.objects.all()
        resource_name = "resource_group"

resources = Api()
resources.register(User())
resources.register(Group())
resources.register(RodsEnvironment())
resources.register(AncillaryResource())
resources.register(DataResource())
resources.register(ResourceGroup())


class Style(AbstractPageResource):
    class Meta(BaseMeta):
        queryset = models.Style.objects.all()
        resource_name = "style"


class StyleTemplate(AbstractPageResource):
    class Meta(BaseMeta):
        queryset = models.StyleTemplate.objects.all()
        resource_name = "template"


class StyleTemplateVariable(AbstractPageResource):
    class Meta(BaseMeta):
        queryset = models.StyleTemplateVariable.objects.all()
        resource_name = "variable"

styles = Api()
styles.register(Style())
styles.register(StyleTemplate())
styles.register(StyleTemplateVariable())


class RasterResourceLayer(AbstractPageResource):
    class Meta(BaseMeta):
        queryset = models.RasterResourceLayer.objects.all()
        resource_name = 'raster_layer'


class VectorResourceLayer(AbstractPageResource):
    class Meta(BaseMeta):
        queryset = models.VectorResourceLayer.objects.all()
        resource_name = 'vector_layer'


class AnimatedResourceLayer(AbstractPageResource):
    class Meta(BaseMeta):
        queryset = models.AnimatedResourceLayer.objects.all()
        resource_name = 'animated_layer'


class RenderedLayer(AbstractPageResource):
    class Meta(BaseMeta):
        queryset = models.RenderedLayer.objects.all()
        resource_name = 'rendered_layer'


layers = Api()
layers.register(RasterResourceLayer())
layers.register(VectorResourceLayer())
layers.register(AnimatedResourceLayer())
layers.register(RenderedLayer())
