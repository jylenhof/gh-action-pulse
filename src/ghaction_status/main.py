"""This script scans GitHub Actions workflow and action definition files for 'uses:' statements."""

from ghaction_status.actions import UniqGithubActions
from ghaction_status.full_list_of_existing_actions import FullListOfExistingActions
from ghaction_status.helpers.constants import SEARCH_CONFIGS


def main() -> None:
    """Main function to scan for 'uses:' statements and analyze them."""
    full_list_of_existing_actions = FullListOfExistingActions(
        search_configs=SEARCH_CONFIGS,
    )
    results = full_list_of_existing_actions.get_results()

    uniq_github_actions = UniqGithubActions()
    uniq_github_actions.init_from_full_list(results)

    print("results:", results)

    uniq_github_actions.get_fully_qualified()

    for action in uniq_github_actions.get_actions():
        action_name = action.name
        reference = action.actual.reference
        actual_description_version = (
            action.actual.description if action.actual.description is not None else ""
        )
        actual_description_type = action.actual.description_type
        actual_reference_type = action.actual.type
        actual_date = action.actual.date
        recommended_reference = action.recommended.reference
        recommended_reference_date = action.recommended.date
        recommended_description = action.recommended.description

        print(f"Action: {action_name}")
        print(f"actual_reference_type: {actual_reference_type}")
        print(f"actual_reference: {reference}")
        print(f"actual_description_version: {actual_description_version}")
        print(f"actual_description_type: {actual_description_type}")
        print(f"actual_date: {actual_date}")
        print(f"recommended_reference: {recommended_reference}")
        print(f"recommended_reference_date: {recommended_reference_date}")
        print(f"recommended_description: {recommended_description}")
        print("----")

        # action_name => owner/repo
        # actual_reference_type => tag, sha, branch
        # actual_reference => sha, tag, ou branche
        # real_sha_commit
        # actual_description => bad_version, right_version, bullshit
        # actual_date => date du commit ou date du tag ou date de la branche
        # suggested_description_version => version ou simple description bullshit
