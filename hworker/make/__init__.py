"""Parsing depot objects and basic execution functionality"""
import datetime
import tomllib
from tomllib import loads
from typing import Iterable

from ..check import check, get_result_ID
from ..config import (
    get_runtime_suffix,
    get_validate_suffix,
    get_check_name,
    get_remote_name,
    get_task_info,
)
from ..depot import store, search
from ..depot.objects import Homework, Check, Solution, CheckCategoryEnum, Criteria, CheckResult, UpdateTime
from ..log import get_logger


def get_checks(hw: Homework) -> list[Check]:
    """Get homework checks list

    :param hw: homework object
    :return: checks list
    """
    get_logger(__name__).debug(f"Started check parsing for {hw.ID} homework")
    checks, seen = [], set()
    for check_path, check_content in hw.content.items():
        if check_path.startswith(get_check_name()):
            path_beg, _, suffix = check_path.rpartition(".")
            name = path_beg.rsplit("/", maxsplit=1)[-1]

            if name not in seen:
                content, category = {}, None
                if suffix in get_runtime_suffix():
                    category = CheckCategoryEnum.runtime
                    for suf in get_runtime_suffix():
                        # What to do if there is only one of the tests of in/out pair?
                        content[f"{name}.{suf}"] = hw.content.get(f"{path_beg}.{suf}", b"")
                elif suffix == get_validate_suffix():
                    category = CheckCategoryEnum.validate
                    content = {f"{name}.{suffix}": check_content}
                else:
                    continue

                check = Check(
                    content=content,
                    category=category,
                    ID=f"{hw.USER_ID}:{hw.TASK_ID}/{name}",
                    TASK_ID=hw.TASK_ID,
                    USER_ID=hw.USER_ID,
                    timestamp=hw.timestamp,
                )
                seen.add(name)
                checks.append(check)

    get_logger(__name__).debug(f"Extracted {[check.ID for check in checks]} checks from {hw.ID} homework")
    return checks


def get_solution(hw: Homework) -> Solution:
    """Get solution object from homework

    :param hw: homework object
    :return: solution object
    """
    get_logger(__name__).debug(f"Started solution parsing for {hw.ID} homework")
    content, remote_checks = {}, []
    for path, path_content in hw.content.items():
        if not path.startswith(get_check_name()):
            content[path] = path_content
    try:
        remote_content = loads(hw.content.get(f"{get_check_name()}/{get_remote_name()}", b"").decode("utf-8"))
    except tomllib.TOMLDecodeError:
        remote_content = {}
        get_logger(__name__).warning(f"Incorrect remote content at {hw.ID} homework")

    remote_checks = remote_content.get("remote", {})
    own_checks = {check.ID: [] for check in get_checks(hw)}
    config_checks = get_task_info(hw.TASK_ID).get("checks", {})
    solution_id = f"{hw.USER_ID}:{hw.TASK_ID}"

    get_logger(__name__).debug(f"Extracted {solution_id} solution from {hw.ID} homework")
    return Solution(
        content=content,
        checks=dict(own_checks, **remote_checks, **config_checks),
        ID=solution_id,
        TASK_ID=hw.TASK_ID,
        USER_ID=hw.USER_ID,
        timestamp=hw.timestamp,
    )


def parse_homework_and_store(hw: Homework) -> None:
    """Parse homework to Solution and Checks and store them with depot

    :param hw: homework object
    :return: -
    """
    for cur_check in get_checks(hw):
        if (
            not (previous_check := search(Check, Criteria("ID", "==", cur_check.ID), first=True))
            or cur_check.content != previous_check.content
        ):
            store(cur_check)

    solution = get_solution(hw)
    if (
        not (previous_solution := search(Solution, Criteria("ID", "==", solution.ID), first=True))
        or solution.content != previous_solution.content
    ):
        store(solution)


def parse_all_stored_homeworks() -> None:
    """Parse all actual homeworks to Solution and Checks and store them with depot

    :return: -
    """
    get_logger(__name__).info("Parse and store all homeworks...")
    hws = search(Homework, actual=True)
    for hw in hws:
        parse_homework_and_store(hw)


def run_solution_checks_and_store(solution: Solution) -> None:
    """Run all given solution checks and store results in depot

    :param solution: solution to run checks
    :return: -
    """
    get_logger(__name__).debug(f"Run all checks of {solution.ID} solution")

    for check_name in solution.checks:
        checker = search(Check, Criteria("ID", "==", check_name), first=True)
        # TODO checker may be None
        # TODO remove this if
        if checker is None:
            continue
        check_result = check(checker, solution)
        # TODO remove this if
        if check_result is None:
            continue
        store(check_result)


def check_all_solutions() -> None:
    """Run all solution checks for every actual solution and store results in depot

    :return: -
    """
    store(UpdateTime(name="Check run", timestamp=datetime.datetime.now().timestamp()))
    get_logger(__name__).info("Run all checks on all solutions...")

    solutions = search(Solution, actual=True)
    for solution in solutions:
        run_solution_checks_and_store(solution)


def check_new_solutions() -> None:
    """Run new solution checks for every actual solution and store results in depot

    :return: -
    """
    store(UpdateTime(name="Check run", timestamp=datetime.datetime.now().timestamp()))
    get_logger(__name__).info("Run new checks on all solutions...")

    solutions: Iterable[Solution] = search(Solution, actual=True)

    for solution in solutions:
        for check_name in solution.checks:
            checker: Check = search(Check, Criteria("ID", "==", check_name), first=True)
            # Not null because solutions and checks parsed together
            result_obj: CheckResult = search(
                CheckResult, Criteria("ID", "==", get_result_ID(solution=solution, checker=checker)), first=True
            )

            if result_obj is None or max(solution.timestamp, checker.timestamp) > result_obj.timestamp:
                new_result = check(checker, solution)
                if new_result is None:
                    continue
                store(new_result)
