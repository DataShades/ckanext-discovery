# encoding: utf-8

"""
Tests for ``ckanext.discovery.plugins.search_suggestions``.
"""

from __future__ import (
    absolute_import,
    division,
    print_function,
    unicode_literals,
)

import pytest
import mock

from ckan.model.meta import Session
import ckan.plugins.toolkit as toolkit
import ckan.tests.helpers as helpers
from ckan.plugins import implements, SingletonPlugin

from ...plugins.search_suggestions.model import (
    create_tables,
    SearchTerm,
    CoOccurrence,
)
from ...plugins.search_suggestions import (
    SearchQuery,
    preprocess_search_term,
    reprocess,
    log as search_suggestions_log,
)
from ...plugins.search_suggestions.interfaces import ISearchTermPreprocessor
from .. import (
    changed_config,
    assert_anonymous_access,
    with_plugin,
    temporarily_enabled_plugin,
)


def search_history(s=""):
    """
    Set the search history.

    The previous search history is cleared and replaced by the search
    queries given in the string ``s``. Each line of ``s`` contains a
    single search query. If ``preprocess`` is False then each line is
    simply split at whitespace. Otherwise the usual query splitting and
    term-postprocessing is used.
    """
    SearchTerm.query().delete()
    Session.commit()
    for string in s.splitlines():
        SearchQuery(string).store()


def assert_empty_search_history():
    """
    Assert that the search history is empty.
    """
    terms = [t.term for t in SearchTerm.query()]
    assert len(terms) == 0


def suggest(q):
    """
    Shortcut for discovery_search_suggest.
    """
    return helpers.call_action("discovery_search_suggest", q=q)


def assert_suggestions(query, suggestions):
    """
    Assert that a certain query gets the expected suggestions.
    """
    results = suggest(query)
    assert [d["value"] for d in results] == suggestions


@pytest.mark.usefixtures("clean_db")
class TestDiscoverySearchSuggest(object):
    """
    Tests for discovery_search_suggest action function.
    """

    def test_no_query(self):
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action("discovery_search_suggest")

    def test_max_content_words(self):
        """
        Only the last 4 complete query terms are taken into account.
        """
        search_history(
            """
            fox chicken
            wolf sheep
        """
        )
        # Last word incomplete
        q = "wolf fox unknown1 unknown2 unknown3 unknown4"
        assert_suggestions(q, [q + " chicken"])

        # Last word complete
        q = "wolf unknown1 unknown2 unknown3 fox "
        assert_suggestions(q, [q + "chicken"])

        # Earlier terms are not re-suggested even if they are ignored
        # when generating suggestions
        assert_suggestions("sheep wolf unknown1 unknown2 unknown4 ", [])

    def test_last_word_complete(self):
        """
        Extensions but no auto-completion if the last word is complete.
        """
        search_history(
            """
            caterpillar
            cat dog
        """
        )
        assert_suggestions("cat ", ["cat dog"])

    def test_completed_terms_more_important_than_autocomplete(self):
        """
        When ranking extensions, complete context words are more
        important than auto-complete suggestions.
        """
        search_history(
            """
            dog wolf
            cat chicken
        """
        )
        q = "dog ca"
        assert_suggestions(
            "dog ca", ["dog cat", "dog cat wolf", "dog cat chicken"]
        )

    def test_limit(self):
        """
        The maximum number of suggestions is configurable.
        """
        search_history(
            """
            badger
            baboon
            bat
            bee
            bear
            beaver
            bison
        """
        )
        KEY = "ckanext.discovery.search_suggestions.limit"
        # Default is 4
        assert len(suggest("b")) == 4

        # Explicit limit
        for limit in range(8):
            with changed_config(KEY, limit):
                assert len(suggest("b")) == limit

        # Make sure a too high limit doesn't break things
        with changed_config(KEY, 10):
            assert len(suggest("b")) == 7

    def test_markup(self):
        """
        Suggestions contain both markup and plaintext.
        """
        search_history(
            """
            bee baboon
            bear badger
        """
        )
        q = "be"
        results = suggest(q)
        for item in results:
            value = item["value"]
            label = item["label"]
            assert value.startswith(q)
            assert label.startswith(q)
            n = len(q)
            assert "<strong>{}</strong>".format(value[n:]) == label[n:]

    def test_anonymous_access(self):
        """
        discovery_search_suggest can be used anonymously.
        """
        assert_anonymous_access("discovery_search_suggest", q="dummy")

    def test_empty_query(self):
        """
        An empty query returns no suggestions.
        """
        assert suggest("") == []

    def test_no_automcompletion_for_pseudo_complete_term(self):
        """
        If the last word matches a term but is not followed by a space
        then that term is not suggested as an auto-completion.
        """
        search_history(
            """
            cat
            caterpillar
        """
        )
        assert_suggestions("cat", ["caterpillar"])

    def test_stripped_characters(self):
        """
        If the query ends with characters that are removed by the
        normalization then they are removed from the suggestions, too.
        """
        search_history(
            """
            cat mouse
        """
        )
        assert_suggestions("cat mo!", ["cat mouse"])


class TestSearchQuery(object):
    """
    Tests for ``SearchQuery``.
    """

    def test_conversion_to_lowercase(self):
        """
        Search queries are converted to lower-case.
        """
        assert SearchQuery("FOO! bar?").string == "foo! bar?"

    def test_query_splitting(self):
        """
        Query strings are correctly split into words.
        """
        cases = [
            ["single-word-with-hyphens", "single-word-with-hyphens"],
            ["-- trailing- -leading - -- ---", "trailing leading"],
            ["1-2 3--4 -5 6- 7", "1-2 3 4 5 6 7"],
            ["\n \t some\twhite\nspace  \t \n", "some white space"],
            ["Ünïçödè çháraċtèrs", "ünïçödè çháraċtèrs"],
            ["!ä_b?c=d<è>f:g#h(i)j[k]", "ä b c d è f g h i j k"],
        ]
        for string, expected in cases:
            assert SearchQuery(string).words == expected.split()

    @mock.patch(
        "ckanext.discovery.plugins.search_suggestions.preprocess_search_term",
        return_value="dog",
    )
    def test_preprocessing(self, preprocess_search_term):
        """
        Query words are preprocessed via ``preprocess_search_term``.
        """
        SearchQuery("fox dog chicken")
        assert preprocess_search_term.mock_calls == [
            mock.call("fox"),
            mock.call("dog"),
            mock.call("chicken"),
        ]

    def test_is_last_word_complete(self):
        """
        Completion status of last word is computed correctly.
        """
        cases = [
            ["", True],
            [" ", True],
            ["dog fox ", True],
            ["dog fox", False],
        ]
        for string, expected in cases:
            assert SearchQuery(string).is_last_word_complete == expected

    def test_last_word(self):
        """
        Last word is computed correctly.
        """
        cases = [
            ["dog", "dog"],
            ["dog fox", "fox"],
            ["dog fox wolf", "wolf"],
            ["dog ", "dog"],
            ["dog\t", "dog"],
            ["dog\n", "dog"],
            ["fox dog ", "dog"],
            ["fox dog\t", "dog"],
            ["fox dog\n", "dog"],
        ]
        for string, expected in cases:
            assert SearchQuery(string).last_word == expected

    def test_last_word_for_empty_query(self):
        """
        Can't get the last word of an empty query
        """
        with pytest.raises(IndexError):
            SearchQuery("  \t \n  ").last_word

    def test_store(self):
        """
        Queries are stored correctly.
        """
        search_history()
        SearchQuery("dog cat").store()
        SearchQuery("wolf dog fox").store()
        SearchQuery("chicken").store()
        SearchQuery("dog cat chicken").store()
        assert SearchTerm.get_or_create(term="dog").count == 3
        assert SearchTerm.get_or_create(term="cat").count == 2
        assert SearchTerm.get_or_create(term="wolf").count == 1
        assert SearchTerm.get_or_create(term="fox").count == 1
        assert SearchTerm.get_or_create(term="chicken").count == 2
        assert CoOccurrence.for_words("dog", "cat").count == 2
        assert CoOccurrence.for_words("wolf", "dog").count == 1
        assert CoOccurrence.for_words("wolf", "fox").count == 1
        assert CoOccurrence.for_words("dog", "fox").count == 1
        assert CoOccurrence.for_words("dog", "chicken").count == 1
        assert CoOccurrence.for_words("cat", "chicken").count == 1
        assert CoOccurrence.for_words("cat", "chicken").count == 1
        assert CoOccurrence.for_words("wolf", "chicken").count == 0
        assert CoOccurrence.for_words("fox", "chicken").count == 0
        assert CoOccurrence.for_words("fox", "cat").count == 0
        assert CoOccurrence.for_words("wolf", "cat").count == 0


class MockSearchTermPreprocessor(SingletonPlugin):
    """
    Helper for ``TestPreprocessSearchTerm`` and ``TestReprocess``.
    """

    implements(ISearchTermPreprocessor)

    def preprocess_search_term(self, term):
        if term == "stopword":
            return False
        if term == "bad-word":
            return ""
        if term == "replace":
            return "-Ä_b-c$z2*3 f-"
        if term == "error":
            raise ValueError("Handle me, please!")
        return term


class TestPreprocessSearchTerm(object):
    """
    Test ``preprocess_search_term``.
    """

    @with_plugin(MockSearchTermPreprocessor)
    def test_preprocess_search_term(self, plugin):
        cases = [
            ["stopword", False],
            ["bad-word", False],
            ["replace", "äb-cz23f"],
            ["-Ä_b-c$z2*3 f-", "äb-cz23f"],
        ]
        for term, expected in cases:
            assert preprocess_search_term(term) == expected


class TestReprocess(object):
    """
    Test ``reprocess``.
    """

    def test_reprocess(self):
        search_history("stopword bad-word replace other")
        with temporarily_enabled_plugin(MockSearchTermPreprocessor):
            reprocess()
        terms = set(t.term for t in SearchTerm.query())
        assert terms == {"äb-cz23f", "other"}
        cooccs = set(
            (c.term1.term, c.term2.term) for c in CoOccurrence.query()
        )
        assert cooccs == {("other", "äb-cz23f")}


class TestISearchTermPreprocessor(object):
    """
    Test ``ISearchTermPreprocessor``.
    """

    def test_default_implementation(self):
        plugin = ISearchTermPreprocessor()
        assert plugin.preprocess_search_term("cat") == "cat"


@pytest.mark.usefixtures("clean_db")
class TestQueryStorage(object):
    """
    Test automatic search query storage.
    """

    def web_request(self, app, controller, action, **kwargs):
        """
        Perform a web-request.

        All keyword arguments are passed as URL-parameters to the given
        controller action.

        Returns the response.
        """
        url = toolkit.h.url_for(controller=controller, action=action)
        return app.get(url, params=kwargs)

    def test_text_search(self, app):
        """
        Text searches are stored.
        """
        search_history()
        self.web_request(app, "package", "search", q="dog fox")
        self.web_request(app, "package", "search", q="dog cat")
        assert SearchTerm.get_or_create(term="dog").count == 2
        assert SearchTerm.get_or_create(term="cat").count == 1
        assert SearchTerm.get_or_create(term="fox").count == 1
        assert CoOccurrence.for_words("dog", "cat").count == 1
        assert CoOccurrence.for_words("dog", "fox").count == 1
        assert CoOccurrence.for_words("fox", "cat").count == 0

    def test_search_by_tag(self, app):
        """
        Searches by tag only are not stored.
        """
        search_history()
        self.web_request(app, "package", "search", tags="dog")
        assert_empty_search_history()

    def test_search_by_group(self, app):
        """
        Searches by group only are not stored.
        """
        search_history()
        self.web_request(app, "package", "search", groups="dog")
        assert_empty_search_history()

    def test_group_search(self, app):
        """
        Group searches are not stored.
        """
        search_history()
        self.web_request(app, "group", "search", q="cat")
        assert_empty_search_history()

    def test_user_search(self, app):
        """
        User searches are not stored.
        """
        search_history()
        self.web_request(app, "user", "search", q="cat")
        assert_empty_search_history()

    def test_api_search(self):
        """
        Package searches via the API are not stored.
        """
        cases = [
            ["package_search", {"q": "cat"}],
            ["resource_search", {"query": "name:cat"}],
            ["tag_search", {"query": "cat"}],
        ]
        search_history()
        for func, params in cases:
            helpers.call_action(func, **params)
            assert_empty_search_history()

    @helpers.change_config(
        "ckanext.discovery.search_suggestions.store_queries", "false"
    )
    def test_disabled_storage(self, app):
        """
        Storing queries can be disabled.
        """
        search_history()
        self.web_request(app, "package", "search", q="dog fox")
        assert_empty_search_history()

    def test_error_handling(self, app, caplog):
        """
        Errors during search term storage are logged and don't cause the
        search to fail.
        """
        with temporarily_enabled_plugin(MockSearchTermPreprocessor):
                # This raises an exception if the request fails, e.g. due to an
                # internal server error caused by our exception not being
                # handled correctly.
                self.web_request(app, "package", "search", q="error")
        assert "An exception occurred while storing a search query" in caplog


class TestUI(object):
    """
    Test web UI.
    """

    def test_resources(self, app):
        """
        JS and CSS resources are included correctly.
        """

        response = app.get("/")
        body = response.body.decode("utf-8")
        assert "search_suggestions.css" in body
        assert "search_suggestions.js" in body

    @helpers.change_config(
        "ckanext.discovery.search_suggestions.provide_suggestions", "false"
    )
    def test_disabled_suggestions(self, app):
        """
        Suggestions can be disabled.
        """
        response = app.get("/")
        assert "search_suggestions.css" not in response
        assert "search_suggestions.js" not in response


@pytest.mark.usefixtures("clean_db")
class TestCreateTables(object):
    """
    Test ``model.create_tables``.
    """

    def test_existing_entries_are_kept(self):
        search_history(
            """
            dog fox
            dog cat
        """
        )
        assert SearchTerm.get_or_create(term="dog").count == 2
        assert SearchTerm.get_or_create(term="fox").count == 1
        assert SearchTerm.get_or_create(term="cat").count == 1
        assert CoOccurrence.for_words("dog", "fox").count == 1
        assert CoOccurrence.for_words("dog", "cat").count == 1
