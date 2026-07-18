import glob
import json
import os
import traceback
from pathlib import Path
from typing import Dict, List

import ray
from cldk import CLDK
from cldk.analysis import AnalysisLevel

from hamster.code_analysis.common import CommonAnalysis, Reachability
from hamster.code_analysis.focal_class_method.focal_class_method import FocalClassMethod
from hamster.code_analysis.model.models import ProjectAnalysis, TestingFramework
from hamster.code_analysis.test_statistics import (
    CallAndAssertionSequenceDetailsInfo,
    SetupAnalysisInfo,
    TestClassAnalysisInfo,
    TestMethodAnalysisInfo,
)
from hamster.utils.pretty import ProgressBarFactory

hamster_analysis_parent_directory = "/home/hamster/xvdc/hamster_results/model"
cldk_analysis_parent_directory = "/home/hamster/xvdc/analysis"
store_path = "/home/hamster/xvdc/hamster_results/new_model"  # Rename accordingly


class HamsterModelAlterer:
    def __init__(self, analysis_path: str, project_analysis_file: str, store_path: str):
        self.analysis = CLDK(language="java").analysis(
            project_path="",
            analysis_backend_path=None,
            analysis_level=AnalysisLevel.symbol_table,
            analysis_json_path=analysis_path,
        )
        with open(project_analysis_file, "r") as f:
            file_content = json.load(f)
            self.project_analysis = ProjectAnalysis.model_validate(file_content)
        self.store_path = store_path
        _, self.application_classes, self.test_utility_classes = CommonAnalysis(
            self.analysis
        ).categorize_classes()

    def alter_focal_class(self):
        """
        Alter the focal class details.
        """
        with ProgressBarFactory.get_progress_bar() as p:
            for cls in p.track(
                self.project_analysis.test_class_analyses,
                total=len(self.project_analysis.test_class_analyses),
            ):
                setup_methods = SetupAnalysisInfo(self.analysis).get_setup_methods(
                    qualified_class_name=cls.qualified_class_name,
                )
                for method in cls.test_method_analyses:
                    (
                        focal_classes,
                        is_application_classed_used,
                        is_ui_test,
                        is_api_test,
                    ) = FocalClassMethod(
                        analysis=self.analysis,
                        application_classes=self.application_classes,
                        test_utility_classes=self.test_utility_classes,
                    ).extract_test_scope(
                        test_qualified_class_name=cls.qualified_class_name,
                        test_method_signature=method.method_signature,
                        setup_methods=setup_methods,
                    )
                    method.focal_classes = focal_classes

    def alter_test_type_focal_classes(self):
        """
        Alter the test type and focal classes.
        """
        self._alter_hamster(
            alter_call_assertion_sequences=False,
            alter_class_fixtures=False,
            alter_test_type=True,
            alter_focal_class=True,
        )

    def alter_focal_classes_test_type_and_project_stats(self):
        """
        Alter focal classes, test type, and project-level statistics.

        Updates:
        - focal_classes and test_type for all TestMethodAnalysis
        - application_class_count, application_method_count, application_cyclomatic_complexity
        - test_class_count, test_method_count
        - test_utility_class_count, test_utility_method_count
        """
        self._alter_hamster(
            alter_call_assertion_sequences=False,
            alter_class_fixtures=False,
            alter_test_type=True,
            alter_focal_class=True,
            alter_project_stats=True,
        )

    def _update_project_stats(self) -> None:
        """Recompute and update project-level statistics from the current analysis."""
        test_class_methods, application_classes, test_utility_classes = CommonAnalysis(
            self.analysis
        ).categorize_classes()

        # Update application_classes for consistency with other alterations
        self.application_classes = application_classes

        application_method_count = 0
        application_cyclomatic_complexity = 0
        for class_name in application_classes:
            methods = self.analysis.get_methods_in_class(class_name)
            application_method_count += len(methods)
            for method_details in methods.values():
                if method_details.cyclomatic_complexity:
                    application_cyclomatic_complexity += (
                        method_details.cyclomatic_complexity
                    )

        test_utility_method_count = 0
        for class_name in test_utility_classes:
            methods = self.analysis.get_methods_in_class(class_name)
            test_utility_method_count += len(methods)

        test_class_count = len(test_class_methods)
        test_method_count = sum(len(methods) for methods in test_class_methods.values())

        self.project_analysis.application_class_count = len(application_classes)
        self.project_analysis.application_method_count = application_method_count
        self.project_analysis.application_cyclomatic_complexity = (
            application_cyclomatic_complexity
        )
        self.project_analysis.test_class_count = test_class_count
        self.project_analysis.test_method_count = test_method_count
        self.project_analysis.test_utility_class_count = len(test_utility_classes)
        self.project_analysis.test_utility_method_count = test_utility_method_count

    def _alter_hamster(
        self,
        *,
        alter_call_assertion_sequences: bool,
        alter_class_fixtures: bool,
        alter_test_type: bool,
        alter_focal_class: bool,
        alter_project_stats: bool = False,
    ) -> None:
        if alter_test_type != alter_focal_class:
            raise NotImplementedError(
                "alter_test_type and alter_focal_class must both be True or False."
            )

        if (
            not alter_call_assertion_sequences
            and not alter_class_fixtures
            and not alter_test_type
            and not alter_focal_class
            and not alter_project_stats
        ):
            return

        if alter_project_stats:
            self._update_project_stats()

        dataset_name = self.project_analysis.dataset_name
        test_class_analysis = None
        call_assertion_details = None
        test_method_analysis = None
        setup_analysis = None

        if alter_class_fixtures:
            test_class_analysis = TestClassAnalysisInfo(
                analysis=self.analysis,
                dataset_name=dataset_name,
                application_classes=self.application_classes,
                test_utility_classes=self.test_utility_classes,
            )

        if alter_call_assertion_sequences:
            call_assertion_details = CallAndAssertionSequenceDetailsInfo(
                self.analysis, dataset_name
            )

        if alter_test_type and alter_focal_class:
            test_method_analysis = TestMethodAnalysisInfo(
                analysis=self.analysis,
                dataset_name=dataset_name,
                application_classes=self.application_classes,
                test_utility_classes=self.test_utility_classes,
            )
            setup_analysis = SetupAnalysisInfo(self.analysis)

        with ProgressBarFactory.get_progress_bar() as p:
            for cls in p.track(
                self.project_analysis.test_class_analyses,
                total=len(self.project_analysis.test_class_analyses),
            ):
                if alter_class_fixtures:
                    assert test_class_analysis is not None
                    cls.setup_analyses = test_class_analysis.get_setup_analysis_info(
                        test_class_qualified_name=cls.qualified_class_name
                    )
                    cls.teardown_analyses = (
                        test_class_analysis.get_teardown_analysis_info(
                            test_class_qualified_name=cls.qualified_class_name
                        )
                    )

                needs_method_iteration = alter_call_assertion_sequences or (
                    alter_test_type and alter_focal_class
                )

                if not needs_method_iteration or not cls.test_method_analyses:
                    continue

                testing_frameworks = cls.testing_frameworks
                setup_methods = None
                if alter_test_type and alter_focal_class:
                    assert setup_analysis is not None
                    setup_methods = setup_analysis.get_setup_methods(
                        qualified_class_name=cls.qualified_class_name,
                    )

                for method in cls.test_method_analyses:
                    if alter_call_assertion_sequences:
                        assert call_assertion_details is not None
                        method.call_assertion_sequences = call_assertion_details.get_call_and_assertion_sequence_details_info(
                            qualified_class_name=cls.qualified_class_name,
                            method_signature=method.method_signature,
                            testing_frameworks=testing_frameworks,
                            test_utility_classes=self.test_utility_classes,
                        )

                    if alter_test_type and alter_focal_class:
                        assert test_method_analysis is not None
                        assert setup_methods is not None
                        test_type, focal_classes = (
                            test_method_analysis.get_test_type_focal_classes(
                                cls.qualified_class_name,
                                method.method_signature,
                                setup_methods,
                            )
                        )
                        method.test_type = test_type
                        method.focal_classes = focal_classes

    def alter_call_assertion_sequences(self):
        """
        Alter the call and assertion sequences.
        """
        self._alter_hamster(
            alter_call_assertion_sequences=True,
            alter_class_fixtures=False,
            alter_test_type=False,
            alter_focal_class=False,
        )

    def alter_class_fixtures(self):
        """
        Refresh setup and teardown analyses for each test class using the latest analysis data.
        """
        self._alter_hamster(
            alter_call_assertion_sequences=False,
            alter_class_fixtures=True,
            alter_test_type=False,
            alter_focal_class=False,
        )

    def alter_call_assertion_sequences_and_class_fixtures(self):
        """
        Update call/assertion sequences and class fixtures in a single pass.
        """
        self._alter_hamster(
            alter_call_assertion_sequences=True,
            alter_class_fixtures=True,
            alter_test_type=False,
            alter_focal_class=False,
        )

    def alter_call_assert_seq_and_class_fixture_and_test_type_and_focal_method(self):
        """Alter all Hamster model facets that depend on test methods and fixtures."""
        self._alter_hamster(
            alter_call_assertion_sequences=True,
            alter_class_fixtures=True,
            alter_test_type=True,
            alter_focal_class=True,
        )

    def alter_testing_framework(self):
        """
        Add two android testing frameworks
        Returns:

        """
        with ProgressBarFactory.get_progress_bar() as p:
            for cls in p.track(
                self.project_analysis.test_class_analyses,
                total=len(self.project_analysis.test_class_analyses),
            ):
                testing_frameworks = CommonAnalysis(
                    self.analysis
                ).get_testing_frameworks_for_class(
                    qualified_class_name=cls.qualified_class_name
                )
                if TestingFramework.ROBOTIUM in testing_frameworks:
                    cls.testing_frameworks.append(TestingFramework.ROBOTIUM)
                if TestingFramework.APPIUM in testing_frameworks:
                    cls.testing_frameworks.append(TestingFramework.APPIUM)

    def alter_method_for_cyclo(self):
        """
        Alter the method's cyclomatic complexity.
        """
        with ProgressBarFactory.get_progress_bar() as p:
            for cls in p.track(
                self.project_analysis.test_class_analyses,
                total=len(self.project_analysis.test_class_analyses),
            ):
                for method in cls.test_method_analyses:
                    qualified_class_name = cls.qualified_class_name
                    method_signature = method.method_signature

                    method_details = self.analysis.get_method(
                        qualified_class_name, method_signature
                    )
                    if not method_details:
                        continue

                    helper_methods: Dict[str, List[str]] = Reachability(
                        self.analysis
                    ).get_helper_methods(
                        qualified_class_name,
                        method_signature,
                        add_extended_class=True,
                        allow_repetition=True,
                        test_utility_classes=self.test_utility_classes,
                    )

                    all_methods = helper_methods
                    all_methods.setdefault(qualified_class_name, []).append(
                        method_signature
                    )

                    cyclomatic_complexity_with_helpers = 0
                    for class_name in all_methods:
                        for method_sig in all_methods[class_name]:
                            method_details = self.analysis.get_method(
                                class_name, method_sig
                            )
                            if not method_details:
                                continue

                            cyclomatic_complexity_with_helpers += (
                                method_details.cyclomatic_complexity
                                if method_details.cyclomatic_complexity
                                else 0
                            )

                    method.cyclomatic_complexity_with_helpers = (
                        cyclomatic_complexity_with_helpers
                    )
                    method.cyclomatic_complexity = (
                        method_details.cyclomatic_complexity
                        if method_details.cyclomatic_complexity
                        else 0
                    )

    def alter_method_for_helper_methods(self):
        """
        Alter method analysis to add helper methods details.
        """
        common_analysis = CommonAnalysis(self.analysis)
        with ProgressBarFactory.get_progress_bar() as p:
            for cls in p.track(
                self.project_analysis.test_class_analyses,
                total=len(self.project_analysis.test_class_analyses),
            ):
                qualified_class_name = cls.qualified_class_name
                all_analyses = cls.test_method_analyses
                for analysis_obj in all_analyses:
                    method_signature = analysis_obj.method_signature

                    method_details = self.analysis.get_method(
                        qualified_class_name, method_signature
                    )
                    if not method_details:
                        continue

                    helper_methods: Dict[str, List[str]] = Reachability(
                        self.analysis
                    ).get_helper_methods(
                        qualified_class_name,
                        method_signature,
                        add_extended_class=True,
                        allow_repetition=True,
                        test_utility_classes=self.test_utility_classes,
                    )
                    all_methods = helper_methods
                    helper_method_count = 0
                    for klazz in helper_methods:
                        helper_method_count += len(helper_methods[klazz])
                    helper_ncloc = sum(
                        common_analysis.get_ncloc(
                            helper_details.declaration, helper_details.code
                        )
                        for class_name in all_methods
                        for method_sig in all_methods[class_name]
                        if (
                            helper_details := self.analysis.get_method(
                                class_name, method_sig
                            )
                        )
                        is not None
                    )
                    analysis_obj.number_of_helper_methods = helper_method_count
                    analysis_obj.helper_method_ncloc = helper_ncloc

    def alter_method_for_ncloc(self):
        """
        Alter method's AND fixture method's NCLOC, and also add NCLOC with helpers.
        """
        common_analysis = CommonAnalysis(self.analysis)
        with ProgressBarFactory.get_progress_bar() as p:
            for cls in p.track(
                self.project_analysis.test_class_analyses,
                total=len(self.project_analysis.test_class_analyses),
            ):
                qualified_class_name = cls.qualified_class_name
                all_analyses = [
                    *cls.setup_analyses,
                    *cls.teardown_analyses,
                    *cls.test_method_analyses,
                ]
                for analysis_obj in all_analyses:
                    method_signature = analysis_obj.method_signature

                    method_details = self.analysis.get_method(
                        qualified_class_name, method_signature
                    )
                    if not method_details:
                        continue

                    ncloc = common_analysis.get_ncloc(
                        method_details.declaration, method_details.code
                    )

                    helper_methods: Dict[str, List[str]] = Reachability(
                        self.analysis
                    ).get_helper_methods(
                        qualified_class_name,
                        method_signature,
                        add_extended_class=True,
                        allow_repetition=True,
                        test_utility_classes=self.test_utility_classes,
                    )

                    all_methods = helper_methods
                    all_methods.setdefault(qualified_class_name, []).append(
                        method_signature
                    )

                    ncloc_with_helpers = sum(
                        common_analysis.get_ncloc(
                            helper_details.declaration, helper_details.code
                        )
                        for class_name in all_methods
                        for method_sig in all_methods[class_name]
                        if (
                            helper_details := self.analysis.get_method(
                                class_name, method_sig
                            )
                        )
                        is not None
                    )

                    analysis_obj.ncloc = ncloc
                    analysis_obj.ncloc_with_helpers = ncloc_with_helpers

    def alter_method_for_ncloc_and_qualified_class(self):
        """
        Alter method's AND fixture method's NCLOC, and also add NCLOC with helpers.
        Also, add qualified class name to each.
        """
        common_analysis = CommonAnalysis(self.analysis)
        with ProgressBarFactory.get_progress_bar() as p:
            for cls in p.track(
                self.project_analysis.test_class_analyses,
                total=len(self.project_analysis.test_class_analyses),
            ):
                qualified_class_name = cls.qualified_class_name
                all_analyses = [
                    *cls.setup_analyses,
                    *cls.teardown_analyses,
                    *cls.test_method_analyses,
                ]
                for analysis_obj in all_analyses:
                    method_signature = analysis_obj.method_signature

                    method_details = self.analysis.get_method(
                        qualified_class_name, method_signature
                    )
                    if not method_details:
                        continue

                    ncloc = common_analysis.get_ncloc(
                        method_details.declaration, method_details.code
                    )

                    helper_methods: Dict[str, List[str]] = Reachability(
                        self.analysis
                    ).get_helper_methods(
                        qualified_class_name,
                        method_signature,
                        add_extended_class=True,
                        allow_repetition=True,
                        test_utility_classes=self.test_utility_classes,
                    )

                    all_methods = helper_methods
                    all_methods.setdefault(qualified_class_name, []).append(
                        method_signature
                    )

                    ncloc_with_helpers = sum(
                        common_analysis.get_ncloc(
                            helper_details.declaration, helper_details.code
                        )
                        for class_name in all_methods
                        for method_sig in all_methods[class_name]
                        if (
                            helper_details := self.analysis.get_method(
                                class_name, method_sig
                            )
                        )
                        is not None
                    )

                    analysis_obj.ncloc = ncloc
                    analysis_obj.ncloc_with_helpers = ncloc_with_helpers
                    analysis_obj.qualified_class_name = qualified_class_name

    def alter_method_for_ncloc_cyclo_qualified(self):
        """
        Alter method's AND fixture method's NCLOC, and also add NCLOC with helpers.
        Also, add qualified class name to each.
        """
        common_analysis = CommonAnalysis(self.analysis)
        with ProgressBarFactory.get_progress_bar() as p:
            for cls in p.track(
                self.project_analysis.test_class_analyses,
                total=len(self.project_analysis.test_class_analyses),
            ):
                qualified_class_name = cls.qualified_class_name
                all_analyses = [
                    *cls.setup_analyses,
                    *cls.teardown_analyses,
                    *cls.test_method_analyses,
                ]
                for analysis_obj in all_analyses:
                    method_signature = analysis_obj.method_signature

                    method_details = self.analysis.get_method(
                        qualified_class_name, method_signature
                    )
                    if not method_details:
                        continue

                    ncloc = common_analysis.get_ncloc(
                        method_details.declaration, method_details.code
                    )
                    cyclo_complexity = (
                        method_details.cyclomatic_complexity
                        if method_details.cyclomatic_complexity
                        else 0
                    )

                    helper_methods: Dict[str, List[str]] = Reachability(
                        self.analysis
                    ).get_helper_methods(
                        qualified_class_name,
                        method_signature,
                        add_extended_class=True,
                        allow_repetition=True,
                        test_utility_classes=self.test_utility_classes,
                    )

                    all_methods = helper_methods
                    all_methods.setdefault(qualified_class_name, []).append(
                        method_signature
                    )

                    ncloc_with_helpers = 0
                    cyclo_with_helpers = 0
                    for class_name in all_methods:
                        for method_sig in all_methods[class_name]:
                            if (
                                helper_details := self.analysis.get_method(
                                    class_name, method_sig
                                )
                            ) is not None:
                                ncloc_with_helpers += common_analysis.get_ncloc(
                                    helper_details.declaration, helper_details.code
                                )
                                cyclo_with_helpers += (
                                    helper_details.cyclomatic_complexity
                                    if helper_details.cyclomatic_complexity
                                    else 0
                                )

                    analysis_obj.ncloc = ncloc
                    analysis_obj.ncloc_with_helpers = ncloc_with_helpers
                    analysis_obj.cyclomatic_complexity = cyclo_complexity
                    analysis_obj.cyclomatic_complexity_with_helpers = cyclo_with_helpers
                    analysis_obj.qualified_class_name = qualified_class_name

    def save(self):
        """
        Save the altered project analysis to the store path.
        """
        project_analysis_str = self.project_analysis.model_dump_json()
        output_dir = Path(self.store_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        with open(self.store_path, "w") as f:
            f.write(project_analysis_str)


@ray.remote
def alter_hamster_model(file):
    try:
        directory_name = (
            file.replace(hamster_analysis_parent_directory, "")
            .replace("hamster.json", "")
            .replace("/", "")
        )
        analysis_path = os.path.join(
            cldk_analysis_parent_directory, directory_name, "symbol_table"
        )
        store_path_file = file.replace(hamster_analysis_parent_directory, store_path)

        alterer = HamsterModelAlterer(
            analysis_path=analysis_path,
            project_analysis_file=file,
            store_path=store_path_file,
        )

        # Choose which alterations to perform
        # alterer.alter_focal_class()
        # alterer.alter_test_type_focal_classes()
        # alterer.alter_call_assertion_sequences()
        # alterer.alter_method_for_cyclo()
        # alterer.alter_method_for_ncloc_cyclo_qualified()
        # alterer.alter_method_for_helper_methods()
        # alterer.alter_testing_framework()
        # alterer.alter_class_fixtures()
        # alterer.alter_call_assert_seq_and_class_fixture_and_test_type_and_focal_method()
        alterer.alter_focal_classes_test_type_and_project_stats()

        alterer.save()

    except Exception as e:
        print(f"Error parsing hamster.json from: {file} {e}")


if __name__ == "__main__":
    pattern = os.path.join(hamster_analysis_parent_directory, "**", "hamster.json")
    all_files = glob.glob(pattern, recursive=True)
    print("Loading Hamster analyses from files...")
    print(f"Processing {len(all_files)} total repositories...")
    ray_tasks = [alter_hamster_model.remote(file) for file in all_files]
    try:
        ray.get(ray_tasks)
    except Exception:
        traceback.print_exc()

    print("Completed model generation...")
    ray.shutdown()
