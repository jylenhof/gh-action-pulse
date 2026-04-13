"""This script scans GitHub Actions workflow and action definition files for 'uses:' statements."""
import os
import pathlib
import re

from github import Auth, Github
from github.GithubException import GithubException


def main() -> None:
    """Main function to scan for 'uses:' statements and analyze them."""
    results: dict[pathlib.Path, list[dict[int, str]]] = {}

    # Configuration for scanning: (directory, glob_pattern, search_keywords)
    search_configs = [
        (".github/workflows", "*.yml", "uses:"),
        (".github/workflows", "*.yaml", "uses:"),
        (".github/actions", "**/*.yml", "uses:", ),
        (".github/actions", "**/*.yaml", "uses:"),
    ]

    for directory, glob_pat, keyword in search_configs:
        regex_pattern = re.compile(rf"^ *({keyword})")

        for file_path in pathlib.Path(directory).glob(glob_pat):
            matches = []
            with file_path.open() as f:
                for line_num, line in enumerate(f, 1):
                    if regex_pattern.search(line):
                        matches.append({line_num: line.strip()})
            if matches:
                results[file_path] = matches

    # Use a set of tuples to automatically handle uniqueness
    unique_actions: set[tuple[str, str, str | None]] = set()

    # Regex captures: 1. Action name, 2. Version, 3. Optional description after '#'
    action_pattern = re.compile(r"^\s*uses:\s*([^@\s]+)@([^\s#]+)(?:\s+#\s+(.+))?")

    for file_path, matches in results.items():
        for match_dict in matches:
            for line_num, line in match_dict.items():
                if match := action_pattern.search(line):
                    if match.group(3) is not None:
                        unique_actions.add((match.group(1), match.group(2), match.group(3)))
                    else:
                        unique_actions.add((match.group(1), match.group(2), None))

    print("results:",results)
    print("unique_actions:",unique_actions)

    for action in unique_actions:
        action_name = action[0]
        reference = action[1]
        actual_description_version = action[2] if action[2] is not None else ""
        actual_description_type = None
        actual_reference_type = None
        actual_date = None
        auth = Auth.Token(os.environ["GITHUB_TOKEN"])
        g = Github(auth=auth)
        repo = g.get_repo(action_name)
        try:
            commit = repo.get_commit(reference)
        except GithubException:
            commit = None

        if commit:
            actual_date = commit.commit.committer.date
            actual_reference_type = "sha"
            if actual_description_version!="":
                try:
                    ref = repo.get_git_ref(f"tags/{actual_description_version}")
                except GithubException:
                    ref = None
                finally:
                    if ref:
                        actual_description_type = "tag"
                    else:
                        try:
                            ref = repo.get_git_ref(f"heads/{actual_description_version}")
                        except GithubException:
                            ref = None
                        finally:
                            if ref:
                                actual_description_type = "branch"
                            else:
                                actual_description_type = "bullshit"
        else:
            ref = repo.get_git_ref(f"tags/{reference}")
            if ref:
                actual_reference_type = "tag"
            else:
                ref = repo.get_git_ref(f"heads/{reference}")
                if ref:
                    actual_reference_type = "branch"

        print(f"Action: {action_name}")
        print(f"actual_reference_type: {actual_reference_type}")
        print(f"actual_reference: {reference}")
        print(f"actual_description_version: {actual_description_version}")
        print(f"actual_description_type: {actual_description_type}")
        print(f"actual_date: {actual_date}")
        print("----")

        # action_name => owner/repo
        # actual_reference_type => tag, sha, branch
        # actual_reference => sha, tag, ou branche
        # real_sha_commit
        # actual_description => bad_version, right_version, bullshit
        # actual_date => date du commit ou date du tag ou date de la branche
        # suggested_description_version => version ou simple description bullshit 
