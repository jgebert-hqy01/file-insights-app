"""Resolves the signed-in teammate from the App Service auth header.

App Service Authentication (Entra ID) sets X-MS-CLIENT-PRINCIPAL-NAME on every
request once a user has signed in; this module never implements its own
login. Locally, where App Service isn't in front of the app, it falls back to
an explicit env var or the OS account running the process.
"""
import getpass
import os

import streamlit as st

_HEADER_NAME = "X-MS-CLIENT-PRINCIPAL-NAME"


def get_signed_in_user() -> str:
    headers = getattr(st.context, "headers", None) or {}
    header_user = headers.get(_HEADER_NAME)
    if header_user:
        return header_user
    return os.environ.get("LOCAL_DEV_USER", getpass.getuser())
