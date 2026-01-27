#!/usr/bin/env python3
"""
Setup script for creating a standalone Mac application of the Payroll Processor.

Usage:
    python setup.py py2app
"""

from setuptools import setup
import sys
import os

# Add current directory to path to import our modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

APP = ['payroll_gui.py']
DATA_FILES = [
    ('', ['process_payroll.py', 'create_employee_reports.py']),
]

OPTIONS = {
    'argv_emulation': False,  # Disable to avoid Carbon framework issues
    'plist': {
        'LSUIElement': False,  # Show app in dock
        'CFBundleName': 'Payroll Processor',
        'CFBundleDisplayName': 'Payroll Processor',
        'CFBundleGetInfoString': "Greek Payroll Processing Application",
        'CFBundleIdentifier': 'com.payrollprocessor.app',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHumanReadableCopyright': 'Copyright © 2025 Payroll Processor',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.12.0',
        'CFBundleDocumentTypes': [
            {
                'CFBundleTypeExtensions': ['zip'],
                'CFBundleTypeName': 'ZIP Archive',
                'CFBundleTypeRole': 'Viewer',
                'LSItemContentTypes': ['public.zip-archive'],
            }
        ],
        'UTExportedTypeDeclarations': [
            {
                'UTTypeIdentifier': 'public.zip-archive',
                'UTTypeDescription': 'ZIP Archive',
                'UTTypeConformsTo': ['public.archive'],
                'UTTypeTagSpecification': {
                    'public.filename-extension': ['zip'],
                    'public.mime-type': ['application/zip'],
                }
            }
        ]
    },
    'packages': ['tkinter', 'tkinterdnd2', 'pandas', 'xlsxwriter'],
    'includes': [
        'tkinter', 'tkinter.ttk', 'tkinter.filedialog', 'tkinter.messagebox',
        'tkinterdnd2', 'pandas', 'xlsxwriter', 'threading', 'tempfile',
        'subprocess', 're', 'os', 'datetime'
    ],
    'excludes': ['PyQt4', 'PyQt5', 'matplotlib', 'numpy', 'Carbon'],
    'iconfile': 'app_icon.icns',  # We'll create this
    'resources': [],
    'optimize': 1,  # Reduced optimization to avoid issues
    'no_strip': True,  # Don't strip debug symbols
    'site_packages': True,  # Include site-packages
}

setup(
    name='Payroll Processor',
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
    install_requires=[
        'tkinterdnd2',
        'pandas',
        'xlsxwriter',
    ],
)