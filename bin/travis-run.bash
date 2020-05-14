#!/bin/bash
set -e

pytest --ckan-ini=subdir/test.ini --cov=ckanext.scheming ckanext/scheming/tests
