from setuptools import setup
import setup_translate

pkg = 'Extensions.Bitrate'
setup(name='enigma2-plugin-extensions-bitrate',
       version='1.0',
       description='Bitrate',
       package_dir={pkg: 'Bitrate'},
       packages=[pkg],
       package_data={pkg: ['images/*.png', '*.png', '*.xml', 'locale/*/LC_MESSAGES/*.mo']},
       cmdclass=setup_translate.cmdclass,  # for translation
      )
