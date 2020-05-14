# encoding: utf-8

"""
Tests for ``ckanext.discovery.plugins.similar_datasets``.
"""

from __future__ import (
    absolute_import,
    division,
    print_function,
    unicode_literals,
)
import pytest
import ckan.plugins.toolkit as tk

from bs4 import BeautifulSoup

import ckan.tests.factories as factories

from ...plugins.similar_datasets import get_similar_datasets
from .. import changed_config, purge_datasets


@pytest.mark.usefixtures("clean_db")
class SimilarDatasetsTestBase(object):
    @pytest.fixture(autouse=True)
    def setup_data(self):
        self.datasets = [
            factories.Dataset(title="cat dog wolf"),
            factories.Dataset(title="cat dog fox"),
            factories.Dataset(title="cat fox wolf"),
            factories.Dataset(title="cat dog"),
            factories.Dataset(title="dog wolf"),
            factories.Dataset(title="cat"),
            factories.Dataset(title="dolphin"),
        ]


class TestGetSimilarDatasets(SimilarDatasetsTestBase):
    """
    Test ``get_similar_datasets``.
    """

    def assert_not_similar(self, datasets):
        """
        Assert that datasets are not similar to the first test dataset.
        """
        max_num = len(self.datasets) + len(datasets)
        similar = get_similar_datasets(self.datasets[0]["id"], max_num=max_num)
        ids = set(dataset["id"] for dataset in similar)
        for dataset in datasets:
            assert dataset["id"] not in ids

    def test_normal_call(self):
        similar = get_similar_datasets(self.datasets[0]["id"])
        ids = set(dataset["id"] for dataset in similar)
        expected = set(dataset["id"] for dataset in self.datasets[1:6])
        assert ids == expected

    def test_not_existing_dataset(self):
        """
        The list of similar datasets of a not-existing dataset is empty.
        """
        assert get_similar_datasets("this-id-does-not-exist") == []

    def test_max_num(self):
        """
        The maximum number of results can be set.
        """
        id = self.datasets[0]["id"]
        assert len(get_similar_datasets(id)) == 5  # Default is 5
        for max_num in [0, 1, 2, 5, 6, 10]:
            assert len(get_similar_datasets(id, max_num=max_num)) == min(
                len(self.datasets) - 1, max_num
            )

    def test_other_site_id(self):
        """
        Datasets with a different site ID are ignored.
        """
        with changed_config("ckan.site_id", "a-different-instance"):
            other_site = factories.Dataset(title=self.datasets[0]["title"])
        self.assert_not_similar([other_site])

    def test_other_dataset_type(self):
        """
        Non-dataset packages are ignored.
        """
        non_dataset = factories.Dataset(
            title=self.datasets[0]["title"], type="not-a-dataset"
        )
        self.assert_not_similar([non_dataset])

    def test_not_active(self):
        """
        Datasets that are not active are ignored.
        """
        deleted = factories.Dataset(
            title=self.datasets[0]["title"], state="deleted"
        )
        draft = factories.Dataset(
            title=self.datasets[0]["title"], state="draft"
        )
        self.assert_not_similar([deleted, draft])

    def test_not_public(self):
        """
        Datasets that are not public are ignored.
        """
        org = factories.Organization()
        private = factories.Dataset(
            title=self.datasets[0]["title"], owner_org=org["id"], private=True
        )
        self.assert_not_similar([private])


class TestUI(SimilarDatasetsTestBase):
    """
    Test web UI.
    """

    def make_soup(self, app, **kwargs):

        url = tk.h.url_for(**kwargs)
        response = app.get(url)
        body = response.body.decode("utf-8")
        return BeautifulSoup(body)

    def test_package_read_template(self, app):
        """
        Similar datasets are listed on the dataset view.
        """
        soup = self.make_soup(
            app, controller="package", action="read", id=self.datasets[0]["id"]
        )
        section = soup.find("section", class_="similar-datasets")
        assert section is not None

    def test_no_similar_datasets(self, app):
        """
        If there are no similar datasets then no list is shown at all.
        """
        purge_datasets()
        dataset = factories.Dataset()
        soup = self.make_soup(
            app, controller="package", action="read", id=dataset["id"]
        )
        section = soup.find("section", class_="similar-datasets")
        assert section is None

    def test_disabled_suggestions(self, app):
        """
        The maximum number of listed similar datasets can be configured.
        """
        n = len(self.datasets)

        def assert_number_of_items(expected):
            soup = self.make_soup(
                app,
                controller="package",
                action="read",
                id=self.datasets[0]["id"],
            )
            section = soup.find("section", class_="similar-datasets")
            if expected == 0:
                assert section is None
            else:
                items = section.ul.find_all("li")
                assert len(items) == min(n - 1, expected)

        assert_number_of_items(5)  # Default value
        key = "ckanext.discovery.similar_datasets.max_num"
        for max_num in [0, 1, 2, n - 1, n, n + 1]:
            with changed_config(key, max_num):
                assert_number_of_items(max_num)
