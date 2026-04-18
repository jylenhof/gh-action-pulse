"""This script scans GitHub Actions workflow and action definition files for 'uses:' statements."""

import logging

from gh_action_pulse.actions import UniqGithubActions
from gh_action_pulse.full_list_of_existing_actions import FullListOfExistingActions
from gh_action_pulse.helpers.constants import SEARCH_CONFIGS

logger = logging.getLogger(__name__)


def main() -> None:
    """Main function to scan for 'uses:' statements and analyze them."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    full_list_of_existing_actions = FullListOfExistingActions(
        search_configs=SEARCH_CONFIGS,
    )
    results = full_list_of_existing_actions.get_results()

    uniq_github_actions = UniqGithubActions()
    uniq_github_actions.init_from_full_list(results)

    logger.info("results: %s", results)

    uniq_github_actions.get_fully_qualified()

    for action in uniq_github_actions.get_actions():
        action_name = action.name
        reference = action.actual.reference
        actual_description_version = action.actual.description if action.actual.description is not None else ""
        actual_description_type = action.actual.description_type
        actual_reference_type = action.actual.type
        actual_date = action.actual.date
        recommended_reference = action.recommended.reference
        recommended_reference_date = action.recommended.date
        recommended_description = action.recommended.description

        logger.info("Action: %s", action_name)
        logger.info("actual_reference_type: %s", actual_reference_type)
        logger.info("actual_reference: %s", reference)
        logger.info("actual_description_version: %s", actual_description_version)
        logger.info("actual_description_type: %s", actual_description_type)
        logger.info("actual_date: %s", actual_date)
        logger.info("recommended_reference: %s", recommended_reference)
        logger.info("recommended_reference_date: %s", recommended_reference_date)
        logger.info("recommended_description: %s", recommended_description)
        logger.info("----")
