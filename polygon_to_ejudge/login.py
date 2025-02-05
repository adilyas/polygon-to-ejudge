import getpass
import os

import polygon_cli.config
import requests
import yaml

from .config import EJUDGE_URL, LANG_IDS

ejudge_auth_file = os.path.join(os.path.expanduser('~'), '.config', 'polygon-to-ejudge', 'auth.yaml')

class EjudgeAuthSession:
    def __init__(self, contest_id: int):
        if os.path.exists(ejudge_auth_file):
            with open(ejudge_auth_file, 'r') as fo:
                auth_data = yaml.load(fo, Loader=yaml.BaseLoader)
            self.login = auth_data.get('login')
            self.password = auth_data.get('password')
        else:
            self.login = input('Ejudge login: ')
            self.password = getpass.getpass('Ejudge password: ')
            os.makedirs(os.path.dirname(ejudge_auth_file), exist_ok=True)
            with open(ejudge_auth_file, 'w') as fo:
                auth_data = {
                    'login': self.login,
                    'password': self.password,
                }
                yaml.dump(auth_data, fo, default_flow_style=False)
            print('Ejudge authentication data is stored in {}'.format(ejudge_auth_file))

        self.session = requests.session()
        self.serve_control_url = EJUDGE_URL + '/cgi-bin/new-judge'
        judge_page = self.session.post(
            self.serve_control_url,
            data={"login": self.login,
                  "password": self.password,
                  "contest_id": contest_id,
                  "role": 1,
                  "language": 0,
                  "action_2": ""
            },
        )
        pos = judge_page.text.find('name="SID" value="') + len('name="SID" value="')
        self.sid = judge_page.text[pos:pos + 16]

    def submit_data(
            self,
            data: str,
            lang_id: int,
            problem_id: int,
    ):
        self.session.post(
            EJUDGE_URL + 'cgi-bin/new-judge',
            data={
                'SID': self.sid,
                'problem': str(problem_id),
                'eoln_type': '1',
                'lang_id': lang_id,
                "action_40": "Send!"
            },
            files={'file': data},
            allow_redirects=True
        )

    def submit_file(
            self,
            solution_path: str,
            problem_id: int,
            no_lint=False,
    ):
        try:
            with open(solution_path) as fp:
                data = fp.read()
        except:
            return

        if data is None:
            return

        if solution_path.endswith(".cpp"):
            lang_type = "cpp"
        elif solution_path.endswith(".py"):
            lang_type = "py"
        elif solution_path.endswith(".java"):
            lang_type = "java"
        elif solution_path.endswith("pas") or solution_path.endswith("fpc") or solution_path.endswith("dpr"):
            lang_type = "pas"
        else:
            return

        if no_lint and lang_type == "cpp":
            data_no_lint = []
            for line in data.split('\n'):
                if line.find('*/') == -1:
                    line += "  // NOLINT"
                data_no_lint.append(line)
            data = '\n'.join(data_no_lint)

        if lang_type == "cpp" or lang_type == "java":
            data = '//' + os.path.basename(solution_path) + '\n' + data
        elif lang_type == "py":
            data = '#' + os.path.basename(solution_path) + '\n' + data

        lang_ids = LANG_IDS[lang_type]
        for lang_id in lang_ids:
            self.submit_data(data, lang_id, problem_id)


def logout():
    # TODO: chose login
    try:
        os.remove(polygon_cli.config.authentication_file)
    except:
        pass

    try:
        os.remove(ejudge_auth_file)
    except:
        pass
    polygon_cli.config.login = None


def add_subparsers(subparsers):
    parser_logout = subparsers.add_parser(
        'logout',
        help="Log out of your login in ejudge and polygon"
    )
    parser_logout.set_defaults(func=lambda options: logout())
