# encoding: utf-8

"""
Helpers for testing ``ckanext.discovery``.
"""

from __future__ import (
    absolute_import,
    division,
    print_function,
    unicode_literals,
)

import contextlib
import functools
import re

from ckan.model import Package
from ckan.model.meta import Session
from ckan.tests.helpers import call_action
from ckan.logic import NotAuthorized


try:
    from ckan.tests.helpers import changed_config
except ImportError:
    from ckan.common import config

    # Copied from CKAN 2.7
    @contextlib.contextmanager
    def changed_config(key, value):
        _original_config = config.copy()
        config[key] = value
        try:
            yield
        finally:
            config.clear()
            config.update(_original_config)



# Copied from ckanext-extractor
def call_action_with_auth(action, context=None, **kwargs):
    """
    Call an action with authorization checks.

    Like ``ckan.tests.helpers.call_action``, but authorization are not
    bypassed.
    """
    if context is None:
        context = {}
    context["ignore_auth"] = False
    return call_action(action, context, **kwargs)


# Copied from ckanext-extractor
def assert_anonymous_access(action, **kwargs):
    """
    Assert that an action can be called anonymously.
    """
    context = {"user": ""}
    try:
        call_action_with_auth(action, context, **kwargs)
    except NotAuthorized:
        raise AssertionError(
            '"{}" cannot be called anonymously.'.format(action)
        )


# Adapted from ckanext-extractor
def with_plugin(cls):
    """
    Activate a plugin during a function's execution.

    The plugin instance is passed to the function as an additional
    parameter.
    """

    def decorator(f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            with temporarily_enabled_plugin(cls) as plugin:
                args = list(args) + [plugin]
                return f(*args, **kwargs)

        return wrapped

    return decorator


@contextlib.contextmanager
def temporarily_enabled_plugin(cls):
    """
    Context manager for temporarily enabling a plugin.

    Returns the plugin instance.
    """
    plugin = cls()
    plugin.activate()
    try:
        plugin.enable()
        yield plugin
    finally:
        plugin.disable()


def assert_regex_search(regex, string):
    """
    Assert that a regular expression search finds a match.
    """
    m = re.search(regex, string, flags=re.UNICODE)
    if m is None:
        raise AssertionError(
            "{!r} finds no match in {!r}".format(regex, string)
        )


def purge_datasets():
    """
    Purge all existing datasets.
    """
    for pkg in Session.query(Package):
        call_action("dataset_purge", id=pkg.id)
