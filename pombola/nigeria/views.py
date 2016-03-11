import requests

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

        # Assume we're dealing with a PUN until it's been proved otherwise.
        self.pun = True

        query = self.request.GET.get('q')
        response = requests.get(settings.PU_SEARCH_API_URL, params={'lookup': query})
        if response.status_code == 400:
            self.pun = False
            return context

        if response.status_code == 404:
            return context

        pu_result = response.json()

        # So now we know that the query is a PUN:
        context['raw_query'] = query
        context['query'] = query
        context['area'] = pu_result['area']

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
                area,
                pu_result)

            # work out what level of the PUN we've matched
            context['area_pun_type'] = area['type_name']

            # attempt to populate governor info
            context['governor'] = self.find_governor(context['state'])

            # work out the polygons to match to, may need to go up tree to parents.
            context['federal_constituencies'] = self.get_district_data(
                self.convert_areas_to_places(pu_result['federal_constituencies']),
                "representative"
            )

            context['senatorial_districts'] = self.get_district_data(
                self.convert_areas_to_places(pu_result['senatorial_districts']),
                "senator"
            )

        return context

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

    def get_state(self, matched_pun, state_code, area, pu_result):
        if ":" in matched_pun:
            # look up state
            state_area = pu_result['states'][0]
        else:
            # matched area is the state, convert it to place data
            state_area = area
        return self.convert_area_to_place(state_area)

    def find_governor(self, state):
        if state:
            governor = self.get_people(state, "executive-governor")
            if governor:
                return governor[0][0]

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
