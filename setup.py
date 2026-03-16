from setuptools import setup, find_packages


with open('README.md', 'r') as fi:
    long_description = fi.read()


setup(
    name='tdh-tcd',
    version='2.5.5',

    author='Dmitry Karikh',
    author_email='the.dr.hax@gmail.com',

    description='Twitch Chat Downloader',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/TheDrHax/Twitch-Chat-Downloader',

    install_requires=[
        'requests',
        'progressbar2',
        'iso8601'
    ],

    packages=find_packages(),
    package_data={'tcd': ['example.settings.json']},
    include_package_data=True,

    entry_points='''
    [console_scripts]
    tcd=tcd:main
    ''',

    classifiers=[
        'Environment :: Console',
        'Programming Language :: Python :: 3.6',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Topic :: Utilities'
    ]
)
