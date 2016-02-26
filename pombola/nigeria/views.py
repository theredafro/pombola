import re

import requests
from mapit.models import Area

from django.conf import settings

from pombola.core.models import Place
from pombola.core.views import HomeView
from pombola.info.models import InfoPage
from pombola.search.views import SearchBaseView


class NGHomeView(HomeView):

    def get_context_data(self, **kwargs):
        context = super(NGHomeView, self).get_context_data(**kwargs)

        context['blog_posts'] = InfoPage.objects.filter(
            categories__slug="latest-news",
            kind=InfoPage.KIND_BLOG
        ).order_by("-publication_date")

        # If there is editable homepage content make it available to the templates.
        # Currently only Nigeria uses this, if more countries want it we should
        # probably add a feature flip boolean to the config.
        try:
            page = InfoPage.objects.get(slug="homepage")
            context['editable_content'] = page.content_as_html
        except InfoPage.DoesNotExist:
            context['editable_content'] = None
        return context


class NGSearchView(SearchBaseView):

    def get_template_names(self):
        if self.pun:
            return ['search/poll-unit-number.html']
        else:
            return super(NGSearchView, self).get_template_names()

    def get_context_data(self, **kwargs):
        context = super(NGSearchView, self).get_context_data(**kwargs)

        query = self.request.GET.get('q')
        area_lookup = requests.get(settings.PU_SEARCH_API_URL, params={'lookup': query})
        if area_lookup.status_code is not 200:
            self.pun = False
            return context

        self.pun = True

        # So now we know that the query is a PUN:
        context['raw_query'] = query
        context['query'] = query
        context['area'] = area_lookup.json()

        # If area found find places of interest
        if context['area']:
            area = context['area']

            # Get the area PUN and name to store in context for template
            context['area_pun_code'] = area['codes']['poll_unit']
            context['area_pun_name'] = area['name']

            # Get the place object for the containing state
            context['state'] = self.get_state(
                context['area_pun_code'],
                query[0:2],
                area)

            # work out what level of the PUN we've matched
            context['area_pun_type'] = area['type_name']

            # attempt to populate governor info
            context['governor'] = self.find_governor(context['state'])

            # work out the polygons to match to, may need to go up tree to parents.
            # area_for_polygons = self.find_containing_area(area)
            # if area_for_polygons:
            #     area_polygons = area_for_polygons.polygons.collect()

            #     context['federal_constituencies'] = self.get_district_data(
            #         self.find_matching_places("FED", area_polygons),
            #         "representative"
            #     )

            #     context['senatorial_districts']  = self.get_district_data(
            #         self.find_matching_places("SEN", area_polygons),
            #         "senator"
            #     )
        return context

    def find_matching_places(self, code, polygons):
        """Find MapIt areas of 'code' type that overlap with 'polygons'

        Return every MapIt area of the specifiedE type such that at
        least 50% of polygons (a MultiPolygon) overlaps it; if there
        are no such areas, just return the 5 MapIt areas of the right
        type with the largest overlap
        """

        all_areas = Area.objects.filter(type__code=code, polygons__polygon__intersects=polygons).distinct()

        area_of_original = polygons.area

        size_of_overlap = {}

        # calculate the overlap
        for area in all_areas:
            area_polygons = area.polygons.collect()
            intersection = polygons.intersection(area_polygons)

            size_of_overlap[area] = intersection.area / area_of_original

        # Sort the results by the overlap size; largest overlap first
        all_areas = sorted(all_areas,
                           reverse=True,
                           key=lambda a: size_of_overlap[a])

        # get the most overlapping ones
        likely_areas = [a for a in all_areas if size_of_overlap[a] > 0.5]

        # If there are none display first five (better than nothing...)
        if not likely_areas:
            likely_areas = all_areas[:5]

        return self.convert_areas_to_places(likely_areas)

    def convert_areas_to_places(self, areas):
        places = []
        for area in areas:
            place = self.convert_area_to_place(area)
            if place:
                places.append(place)

        return places

    def convert_area_to_place(self, area):
        try:
            return Place.objects.get(mapit_area_id=area['id'])
        except Place.DoesNotExist:
            return None

    def get_area_from_pun(self, pun):
        """Find MapIt area that matches the PUN."""

        return requests.get(settings.PU_SEARCH_API_URL, params={'lookup': pun}).json()

    def get_state(self, matched_pun, state_code, area):
        if ":" in matched_pun:
            # look up state
            state_area = self.get_area_from_pun(state_code)
        else:
            # matched area is the state, convert it to place data
            state_area = area
        return self.convert_area_to_place(state_area)

    def find_governor(self, state):
        if state:
            governor = self.get_people(state, "executive-governor")
            if governor:
                return governor[0][0]

    def find_containing_area(self, area):
        area_for_polygons = area
        while area_for_polygons and not area_for_polygons.polygons.exists():
            area_for_polygons = area_for_polygons.parent_area
        return area_for_polygons

    def get_district_data(self, districts, role):
        district_list = []
        for district in districts:
            place = {}
            place['district_name'] = district.name
            place['district_url'] = district.get_absolute_url()
            people = self.get_people(district, role)
            if people:
                place['rep_name'] = people[0][0].name
                place['rep_url'] = people[0][0].get_absolute_url()
            district_list.append(place)
        return district_list

    def get_people(self, place, role):
        return place.related_people(
            lambda qs: qs.filter(person__position__title__slug=role))
