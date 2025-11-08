from setuptools import setup, find_packages

# Read the contents of requirements.txt file
with open('requirements.txt') as f:
    requirements = f.read().splitlines()

setup(
    name='queuectl',
    version='0.1.0',
    # Automatically find the 'queue' package
    packages=find_packages(),
    # Include queuectl.py as a top-level module
    py_modules=['queuectl'],
    # Pull dependencies from requirements.txt
    install_requires=requirements,
    # Creates a console script named 'queuectl' that calls the 'app' object inside the 'queuectl' module.
    entry_points={
        'console_scripts': [
            'queuectl = queuectl:app',
        ],
    },
)