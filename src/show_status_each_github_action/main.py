import os
import pathlib
import re

from github import Auth, Github
from github.GithubException import GithubException


def main() -> None:
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
        description_version = action[2] if action[2] is not None else ""

        auth = Auth.Token(os.environ["GITHUB_TOKEN"])
        g = Github(auth=auth)
        repo = g.get_repo(action_name)
        try:
            commit = repo.get_commit(reference)
        except GithubException:
            commit = None
        if commit:
            print(repo.full_name)
            print(commit.commit.committer.date)
            print("description_version:", description_version)
            if description_version!="":
                ref = repo.get_git_ref(f"tags/{description_version}")
                if not ref:
                    ref = repo.get_git_ref(f"heads/{description_version}")
                if ref:
                    print(ref.object.sha)
        else:
            ref = repo.get_git_ref(f"tags/{reference}")
            if not ref:
                ref = repo.get_git_ref(f"heads/{reference}")
            if ref:
                print(repo.full_name)
                print(ref.object.sha)

        print(f"Action: {action_name}, Reference: {reference}, Description: {description_version}")

        # Verifier si reference est un tag ou une branche
        # Sinon, c'est un commit SHA
        # Si commit SHA, on peut chercher si la description contient une référence à un tag ou une branche
        # et on vérifie que le commit SHA correspond à ce tag ou branche
