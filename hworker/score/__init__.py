import datetime
import importlib.util
import inspect
import os
import traceback
from functools import cache
from pathlib import Path


from .. import depot, config
from ..log import get_logger

_module_names = ["task_qualifier", "user_qualifier", "formula"]
_module_objects = [
    depot.objects.TaskQualifier,
    depot.objects.UserQualifier,
    depot.objects.Formula,
]


@cache
def _get_score_directory():
    return config.get_score_info()["score_directory"]


def _get_path_from_name(name: str):
    return Path(_get_score_directory(), f"{name}.py")


def create_files():
    for name in _module_names:
        path = _get_path_from_name(name)
        if not path.exists():
            with open(path, "x") as fp:
                get_logger(__name__).warn(f"Empty {name} file")


@cache
def _get_functions_from_module(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}", Path(_get_score_directory(), f"{name}.py"))
    module = importlib.util.module_from_spec(spec)

    found_funcs = dict()
    for key, value in inspect.getmembers(module):
        if not key.startswith("_") and inspect.isfunction(value):
            found_funcs[key] = value

    return found_funcs


def read_and_import():
    get_logger(__name__).info("Importing user functions...")
    for index, name in enumerate(_module_names):
        found_funcs = _get_functions_from_module(name)

        file_timestamp = os.path.getmtime(_get_path_from_name(name))
        for f_name in found_funcs:
            depot.store(
                _module_objects[index](
                    ID=f"{f_name}",
                    timestamp=file_timestamp,
                    name=f_name,
                    content="",
                )
            )


def _execute_user_func(func, inputs):
    try:
        rating = func(inputs)
    except Exception as e:
        rating = None
        get_logger(__name__).debug(
            f"Error occurred during executing user function\n {''.join(traceback.format_exception(e))}"
        )
    return rating


def perform_qualifiers():
    get_logger(__name__).info("Performing all imported qualifiers...")
    _current_timestamp = datetime.datetime.now().timestamp()
    for USER_ID in config.get_uids():
        for TASK_ID in config.get_tasks_list():
            inputs = list(
                depot.search(
                    depot.objects.CheckResult,
                    depot.objects.Criteria("USER_ID", "==", USER_ID),
                    depot.objects.Criteria("TASK_ID", "==", TASK_ID),
                )
            )
            for f_name, func in _get_functions_from_module("task_qualifier").items():
                rating = _execute_user_func(func, inputs)
                if rating is not None:
                    depot.store(
                        depot.objects.TaskScore(
                            ID=f"{USER_ID}/{TASK_ID}/{f_name}",
                            USER_ID=USER_ID,
                            TASK_ID=TASK_ID,
                            timestamp=_current_timestamp,
                            name=f_name,
                            rating=rating,
                        )
                    )

        inputs = list(depot.search(depot.objects.TaskScore, depot.objects.Criteria("USER_ID", "==", USER_ID)))
        for f_name, func in _get_functions_from_module("user_qualifier").items():
            rating = _execute_user_func(func, inputs)
            if rating is not None:
                depot.store(
                    depot.objects.UserScore(
                        ID=f"{USER_ID}/{f_name}",
                        USER_ID=USER_ID,
                        timestamp=_current_timestamp,
                        name=f_name,
                        rating=rating,
                    )
                )

        inputs = list(depot.search(depot.objects.UserScore, depot.objects.Criteria("USER_ID", "==", USER_ID)))
        for f_name, func in _get_functions_from_module("formula").items():
            rating = _execute_user_func(func, inputs)
            if rating is not None:
                depot.store(
                    depot.objects.FinalScore(
                        ID=f"{USER_ID}", USER_ID=USER_ID, timestamp=_current_timestamp, rating=rating
                    )
                )
