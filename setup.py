try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

with open('README') as file:
    long_description = file.read()

setup(name='tornado-swirl',
      version='0.1',
      url='https://github.com/rduldulao/tornado-swirl',
      zip_safe=False,
      packages=['tornado_swirl'],
      package_data={
        'tornado_swirl': [
          'static/*.*',
          'static/css/*.*',
          'static/images/*.*',
          'static/lib/*.*',
          'static/lib/shred/*.*',
        ]
      },
      description='Extract swagger specs from your tornado project',
      author='Rodolfo Duldulao',
      license='MIT',
      long_description=long_description,
      install_requires=[
        'tornado>=5.1.1',
      ],
)
