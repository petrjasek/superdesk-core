#!/usr/bin/env python3
#
# This file is part of Superdesk.
#
# Copyright 2013-2020 Sourcefabric z.u. and contributors.
#
# For the full copyright and license information, please see the
# AUTHORS and LICENSE files distributed with this source code, or
# at https://www.sourcefabric.org/superdesk/license

from setuptools import setup, find_packages

LONG_DESCRIPTION = "Superdesk Server Core"

install_requires = [
    "eve>=2.0,<2.1",
    "eve-elastic>=7.3,<7.4",
    "flask<2.2",  # based on eve
    "flask-mail>=0.9,<0.10",
    "flask-script==2.0.6",  # deprecated
    "flask-babel>=3.0,<3.1",
    "pillow>=9.2,<9.3",
    "arrow>=1.2,<=1.3",
    "bcrypt>=3.1.1,<3.2",
    "celery[redis]>=4.4.0,<5",
    "redis>=3.2,<3.3",
    "feedparser>=6.0,<6.1",
    "hachoir>=3.2,<3.3",
    "HermesCache>=0.10,<0.11",
    "python-magic>=0.4,<0.5",
    "ldap3>=2.2.4,<2.6",
    "pytz>=2015.4",
    "tzlocal>=2.1,<3",
    "requests>=2.28,<3",
    "boto3>=1.18,<2",
    "websockets>=10.3,<11",
    "mongolock==1.3.4",  # deprecated
    "lxml>=4,<4.7",
    "python-twitter==3.5",
    "chardet>=5.1,<6.0",
    "pymongo>=3.8,<4.0",
    "croniter>=1.3,<1.4",
    "python-dateutil>=2.8,<3.0",
    "unidecode>=1.3,<1.4",
    "authlib>=1.2,<1.3",
    "draftjs-exporter[lxml]<2.2",
    "regex",
    "flask-oidc-ex==0.5.5",
    # to be replaced by stdlib version when we use Python 3.8+
    "typing_extensions>=3.7.4",
    "elastic-apm[flask]>=6.7,<7",
]

package_data = {
    "superdesk": [
        "templates/*.txt",
        "templates/*.html",
        "locators/data/*.json",
        "io/data/*.json",
        "data_updates/*.py",
        "data_updates/*.js",
        "translations/*.po",
        "translations/*.mo",
    ],
    "apps": [
        "prepopulate/*.json",
        "prepopulate/data_init/*.json",
        "io/data/*.json",
    ],
}

setup(
    name="Superdesk-Core",
    version="2.7.0dev",
    description="Superdesk Core library",
    long_description=LONG_DESCRIPTION,
    author="petr jasek",
    author_email="petr.jasek@sourcefabric.org",
    url="https://github.com/superdesk/superdesk-core",
    license="GPLv3",
    platforms=["any"],
    packages=find_packages(exclude=["tests*", "features*"]),
    package_data=package_data,
    include_package_data=True,
    # setup_requires=["setuptools_scm"],
    install_requires=install_requires,
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Topic :: Internet :: WWW/HTTP :: Dynamic Content",
    ],
)
