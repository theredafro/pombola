from django.contrib.gis.db import models
from django_date_extensions.fields import ApproximateDateField

# tell South how to handle the custom fields 
from south.modelsinspector import add_introspection_rules
add_introspection_rules([], ["^django_date_extensions\.fields\.ApproximateDateField"])
add_introspection_rules([], ["^django.contrib\.gis\.db\.models\.fields\.PointField"])

date_help_text = "Format: '2011-12-31', '31 Jan 2011', 'Jan 2011' or '2011'"

class Person(models.Model):
    first_name      = models.CharField(max_length=100)
    middle_names    = models.CharField(max_length=100, blank=True)
    last_name       = models.CharField(max_length=100)
    slug            = models.SlugField(max_length=200, unique=True, help_text="auto-created from first name and last name")
    gender          = models.CharField(max_length=1, choices=(('m','Male'),('f','Female')) )
    date_of_birth   = ApproximateDateField(blank=True, help_text=date_help_text)
    date_of_death   = ApproximateDateField(blank=True, help_text=date_help_text)
    # religion
    # tribe
    
    def name(self):
        return "%s %s" % ( self.first_name, self.last_name )
    
    def __unicode__(self):
        return "%s %s (%s)" % ( self.first_name, self.last_name, self.slug )

    @models.permalink
    def get_absolute_url(self):
        return ( 'person', [ self.slug ] )

    class Meta:
       ordering = ["slug"]      
    

class Organisation(models.Model):
    name                = models.CharField(max_length=200)
    slug                = models.SlugField(max_length=200, unique=True, help_text="created from name")
    organisation_type   = models.CharField(max_length=50)
    started             = ApproximateDateField(blank=True, help_text=date_help_text)
    ended               = ApproximateDateField(blank=True, help_text=date_help_text)

    def __unicode__(self):
        return "%s (%s)" % ( self.name, self.slug )

    @models.permalink
    def get_absolute_url(self):
        return ( 'organisation', [ self.slug ] )

    class Meta:
       ordering = ["slug"]      


class Place(models.Model):
    name            = models.CharField(max_length=200)
    slug            = models.SlugField(max_length=100, unique=True, help_text="created from name")
    place_type      = models.CharField(max_length=50)
    shape_url       = models.URLField(verify_exists=True, blank=True )
    location        = models.PointField(null=True, blank=True)
    organisation    = models.ForeignKey('Organisation', null=True, blank=True, help_text="use if the place uniquely belongs to an organisation - eg a field office" )

    def __unicode__(self):
        return "%s (%s)" % ( self.name, self.slug )

    @models.permalink
    def get_absolute_url(self):
        return ( 'place', [ self.slug ] )

    class Meta:
       ordering = ["slug"]      


class Position(models.Model):
    person          = models.ForeignKey('Person')
    organisation    = models.ForeignKey('Organisation')
    place           = models.ForeignKey('Place', null=True, blank=True, help_text="use if needed to identify the position - eg add constituency for an 'MP'" )
    title           = models.CharField(max_length=200)
    start_date      = ApproximateDateField(blank=True, help_text=date_help_text)
    end_date        = ApproximateDateField(blank=True, help_text=date_help_text)
    
    def __unicode__(self):
        return "%s (%s at %s)" % ( self.title, self.person.name(), self.organisation.name )

    class Meta:
       ordering = ["title"]      
