import unittest
import doctest
import re
from . import views

from django.test import TestCase
from django_webtest import WebTest
from django.conf import settings

from nose.plugins.attrib import attr
import requests_mock

from mapit.models import Area, CodeType, NameType, Type
from pombola.core.models import (
    Place, PlaceKind, Person, Position, PositionTitle)
from pombola.info.models import InfoPage

# Needed to run the doc tests in views.py

def suite():
    suite = unittest.TestSuite()
    suite.addTest(doctest.DocTestSuite(views))
    return suite

@attr(country='nigeria')
class HomeViewTest(TestCase):

    def test_homepage_context(self):
        response = self.client.get('/')
        self.assertIn('featured_person', response.context)
        self.assertIn('featured_persons', response.context)
        self.assertIn('editable_content', response.context)

@attr(country='nigeria')
class InfoBlogListTest(TestCase):

    def setUp(self):
        self.info_page = InfoPage.objects.create(
            slug='escaping-test',
            kind='blog',
            title='Escaping Test', markdown_content="\nTesting\n\n**Escaped**\n\nContent"
        )

    def tearDown(self):
        self.info_page.delete()

    def test_html_not_escaped(self):
        response = self.client.get('/blog/')
        self.assertNotIn('&lt;p&gt;', response.content)


@requests_mock.mock()
@attr(country='nigeria')
class NGSearchViewTest(WebTest):
    def test_four_part_pun_is_recognised(self, m):
        m.get(settings.PU_SEARCH_API_URL, status_code=404)
        response = self.app.get("/search/?q=01:02:03:04")
        self.assertContains(
            response,
            'No results were found for the poll unit number 01:02:03:04'
        )

    def test_slash_formatted_pun_is_recognised(self, m):
        m.get(settings.PU_SEARCH_API_URL, status_code=404)
        response = self.app.get("/search/?q=01/02/03/04")
        self.assertContains(
            response,
            'No results were found for the poll unit number 01/02/03/04'
        )

    def test_matching_state(self, m):
        m.get(settings.PU_SEARCH_API_URL, json={
            'area': {
                'codes': {
                    'poll_unit': 'ON'
                },
                'id': 30,
                'name': 'Ondo',
                'type_name': 'State',
            },
            'federal_constituencies': [],
            'senatorial_districts': [],
            'states': []})
        response = self.app.get("/search/?q=28/04454/09")
        self.assertContains(
            response,
            'Best match is the State "Ondo" with poll unit number \'ON\''
        )

    def test_matching_lga(self, m):
        m.get(settings.PU_SEARCH_API_URL, json={
            'area': {
                'codes': {
                    'poll_unit': 'ON:4'
                },
                'id': 66,
                'name': 'Akoko South-West',
                'type_name': 'Local Government Area',
            },
            'federal_constituencies': [],
            'senatorial_districts': [],
            'states': [{'id': 42}]})
        response = self.app.get("/search/?q=28/04/09")
        self.assertContains(
            response,
            'Best match is the Local Government Area "Akoko South-West" with poll unit number \'ON:4\''
        )
