from collections import OrderedDict
import os
import shutil
import re
import xml.etree.ElementTree as ET
import zipfile
import random
from bs4 import BeautifulSoup

from polygon_cli import problem
from polygon_cli import config as cli_config

from .common import Config, get_ejudge_contest_dir, UnquotedStr
from .config import PROBLEM_CFG_START, GVALUER_LOCATION, CREATE_STATEMENTS, IMPORT_ALL_SOLUTIONS, CONVERT_EPS, \
    IMG_STYLE, IMG_SRC_PREFIX, TEXTAREA_INPUT, IMPORT_ALL_SOLUTIONS, TMP_DOWNLOAD_DIR_PATTERN
from .gvaluer import generate_valuer
from .statement import import_statement, process_statement_xml


def extract_zip(zip_file, prefix):
    files_list = zip_file.filelist
    for file in files_list:
        if file.filename.startswith(prefix):
            zip_file.extract(file.filename)


def move_file_name(file_name):
    prefix = ''
    if '/' in file_name:
        prefix = file_name[:file_name.rfind('/')]
        file_name = file_name[file_name.rfind('/') + 1:]
    output_file_name = file_name
    if output_file_name.endswith("dpr"):
        output_file_name = output_file_name[:-3] + "pas"
    shutil.copyfile(os.path.join(prefix, file_name), output_file_name)
    file_name = file_name[:file_name.rfind('.')]
    return file_name


def extract_images(statements, src_dir, out_dir):
    st = BeautifulSoup(statements, "xml")
    images = st.find_all("img")
    for img in images:
        try:
            shutil.copyfile(os.path.join(src_dir, img['src']), os.path.join(out_dir, img['src']))
        except Exception as e:
            print(e)
        img['src'] = IMG_SRC_PREFIX + img['src']
        img['style'] = IMG_STYLE

    epses = st.find_all("embed")
    for eps_img in epses:
        name = ''.join([random.choice([str(i) for i in range(10)]) for i in range(10)]) + ".png"
        os.system(CONVERT_EPS.format(
            os.path.join(out_dir, name),
            os.path.join(src_dir, eps_img['src'])
        ))
        img = BeautifulSoup("<img>", features="html.parser")
        img.find('img')['src'] = IMG_SRC_PREFIX + name
        img.find('img')['style'] = IMG_STYLE
        eps_img.replace_with(img)
    return str(st)


def download_problem_package(
        polygon_id: int,
) -> str:
    cli_config.setup_login_by_url('')
    session = problem.ProblemSession("main", polygon_id, None)

    tmp_dir = TMP_DOWNLOAD_DIR_PATTERN.format(suffix=polygon_id)

    if os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir)

    os.chdir(tmp_dir)
    session.download_last_package()

    problem_zip_name = os.listdir(tmp_dir)[0]
    problem_zip_path = os.path.abspath(os.path.join(tmp_dir, problem_zip_name))

    return problem_zip_path

def import_zip_problem(
        ejudge_contest_id: int,
        problem_zip_path: str,
        polygon_id=None,
        short_name=None,
        ejudge_problem_id=None,
        no_offline=False
) -> None:
    contest_dir = get_ejudge_contest_dir(ejudge_contest_id)
    problems_dir = os.path.join(contest_dir, 'problems')

    os.chdir(contest_dir)

    contest_config = Config(ejudge_contest_id)
    old_contest_config = Config(ejudge_contest_id)

    if not ejudge_problem_id:
        max_problem_id = 0
        short_names = []
        for cfg_problem in contest_config.problems:
            if "id" in cfg_problem:
                max_problem_id = max(max_problem_id, int(cfg_problem["id"]))
            if "short_name" in cfg_problem:
                short_names.append(cfg_problem["short_name"])

        if short_name in short_names or short_name is None:
            short_name = None
            for i in range(ord('A'), ord('Z') + 1):
                if chr(i) not in short_names:
                    short_name = chr(i)
                    break
            if short_name is None:
                i = 0
                while short_name is None:
                    if str(i) not in short_names:
                        short_name = str(i)
                        i += 1
        ejudge_problem_id = max_problem_id + 1

    if not os.path.exists(problems_dir):
        os.mkdir(problems_dir)

    problem_zip_name = os.path.basename(problem_zip_path)
    problem_name = problem_zip_name[:problem_zip_name.rfind(".zip")]

    problems = os.listdir(problems_dir)
    if problem_name in problems:
        additional_id = 2
        while "{}-{}".format(problem_name, additional_id) in problems:
            additional_id += 1
        problem_name = "{}-{}".format(problem_name, additional_id)

    try:
        problem_dir = os.path.join(problems_dir, problem_name)
        os.mkdir(problem_dir)
        os.chdir(problem_dir)

        interactor_name = None

        with zipfile.ZipFile(problem_zip_path, "r") as zip_file:
            zip_file.extract('problem.xml')
            xml_file = open('problem.xml', 'r')
            tree = ET.ElementTree(file=xml_file)
            tree = tree.getroot()
            for solution in tree.find('assets').find('solutions'):
                if solution.attrib['tag'] == 'main':
                    solution_name = solution.find('source').attrib['path']
            extract_zip(zip_file, 'solutions/')
            solution_name = move_file_name(solution_name)

            if not IMPORT_ALL_SOLUTIONS:
                shutil.move(os.path.join(problem_dir, 'solutions/'), os.path.join(problem_dir, 'solutions1/'))

            if tree.find('documents'):
                extract_zip(zip_file, 'documents/')

            extract_zip(zip_file, 'files/')
            checker_name = move_file_name(tree.find('assets').find('checker').find('source').attrib['path'])

            if tree.find('assets').find('interactor'):
                interactor_name = move_file_name(tree.find('assets').find('interactor').find('source').attrib['path'])

            for file in tree.find('files').find('resources'):
                move_file_name(file.attrib['path'])

            extract_zip(zip_file, 'tests/')

            if CREATE_STATEMENTS:
                extract_zip(zip_file, 'statement-sections')
                statement_languages = os.listdir(os.path.join(problem_dir, 'statement-sections'))

                problem_xml = ET.Element('problem')

                format_statements = []
                format_examples = []
                informatics_statements = None
                for language in statement_languages:
                    statement_xml = None
                    if language == 'russian':
                        import_statement_res = import_statement(
                            os.path.join(problem_dir, 'statement-sections', 'russian'),
                            'ru_RU',
                        )
                        format_statements = import_statement_res[2] + format_statements
                        format_examples = import_statement_res[3]
                        informatics_statements = import_statement_res[1]
                        statement_xml = import_statement_res[0]
                    if False and language == 'english':
                        import_statement_res = import_statement(
                            os.path.join(problem_dir, 'statement-sections', 'english'),
                            'en_EN',
                        )
                        format_statements = import_statement_res[2] + format_statements
                        format_examples = import_statement_res[3]
                        if informatics_statements is None:
                            informatics_statements = import_statement_res[1]
                        statement_xml = import_statement_res[0]
                    if statement_xml:
                        example = problem_xml.find('examples')
                        if not example:
                            problem_xml.insert(0, statement_xml.find('examples'))
                        problem_xml.insert(0, statement_xml.find('statement'))
                format_statements.extend(format_examples)
                if informatics_statements is not None:
                    informatics_statements_file = open("statements.html", "w")
                    informatics_statements_file.write(informatics_statements)
                    informatics_statements_file.close()
                problem_xml_str = ET.tostring(problem_xml, encoding='utf-8', method='xml').decode('utf-8')
                problem_xml_str = problem_xml_str.format(*format_statements)

                if len(statement_languages) > 0:
                    attachments_dir = os.path.join(problem_dir, 'attachments')
                    os.mkdir(attachments_dir)
                    problem_xml_str = extract_images(
                        problem_xml_str,
                        os.path.join(problem_dir, 'statement-sections', statement_languages[0]),
                        attachments_dir
                    )
                # problem_xml_str = process_statement_xml(problem_xml_str)
                problem_xml_file = open('statements.xml', 'w')
                problem_xml_file.write(problem_xml_str)
                problem_xml_file.close()

        input_file = tree.find('judging').attrib['input-file']
        output_file = tree.find('judging').attrib['output-file']

        russian_name = None
        english_name = None
        any_name = None

        for language in tree.find('names'):
            if language.attrib['language'] == 'russian':
                russian_name = language.attrib['value']
            if language.attrib['language'] == 'english':
                english_name = language.attrib['value']
            any_name = language.attrib['value']

        if not russian_name:
            russian_name = english_name
        if not english_name:
            english_name = russian_name
        if not english_name and not russian_name:
            english_name = any_name
            russian_name = any_name

        memory_limit = int(tree.find('judging').find('testset').find('memory-limit').text)
        memory_limit //= 1024
        if memory_limit % 1024 != 0:
            memory_limit = "{}K".format(memory_limit)
        else:
            memory_limit //= 1024
            if memory_limit % 1024 != 0:
                memory_limit = "{}M".format(memory_limit)
            else:
                memory_limit = "{}G".format(memory_limit // 1024)

        config = OrderedDict()
        problem_config = OrderedDict()

        config['id'] = ejudge_problem_id

        for prob_conf in contest_config.problems:
            if 'abstract' in prob_conf and 'short_name' in prob_conf and prob_conf['short_name'] == "Generic":
                config["super"] = "Generic"

        config['short_name'] = short_name
        config['long_name'] = russian_name
        problem_config['long_name_en'] = english_name
        config['internal_name'] = problem_name
        if polygon_id is not None:
            config['extid'] = 'polygon:{}'.format(polygon_id)
        problem_config['revision'] = tree.attrib['revision']
        if CREATE_STATEMENTS:
            config['xml_file'] = "statements.xml"

        if input_file:
            config['use_stdin'] = False
            config['input_file'] = input_file
        else:
            config['use_stdin'] = True

        if output_file:
            config['use_stdout'] = False
            config['output_file'] = output_file
        else:
            config['use_stdout'] = True

        config['test_pat'] = "%02d"
        config['use_corr'] = True
        config['corr_pat'] = "%02d.a"

        time_limit = int(tree.find('judging').find('testset').find('time-limit').text)
        if time_limit % 1000 == 0:
            config['time_limit'] = time_limit // 1000
        else:
            config['time_limit_millis'] = time_limit
        config['real_time_limit'] = max(5, (time_limit * 2 + 999) // 1000)

        config['max_vm_size'] = UnquotedStr(memory_limit)
        config['max_stack_size'] = UnquotedStr(memory_limit)

        config['check_cmd'] = checker_name
        if interactor_name:
            config['interactor_cmd'] = interactor_name
        config['solution_cmd'] = solution_name

        config['enable_testlib_mode'] = True

        if TEXTAREA_INPUT:
            config['enable_text_form'] = True

        problem_test = tree.find('judging').find('testset').find('tests').find('test')
        if problem_test is not None:
            valuer_config = generate_valuer(tree, 'points' in problem_test.keys(), no_offline)
            if contest_config.common['score_system'].val != 'acm':
                config.update(valuer_config)
                contest_config.common['separate_user_score'] = 1
                shutil.copy(GVALUER_LOCATION, os.path.join(problems_dir, 'gvaluer'))

        try:
            problem_description = open('documents/description.txt', 'r')
            for line in problem_description.readlines():
                if line.startswith('source_header'):
                    config['source_header'] = os.path.join(problem_dir, line.split()[1])
                if line.startswith('source_footer'):
                    config['source_footer'] = os.path.join(problem_dir, line.split()[1])
                if line.startswith('ejudge_config'):
                    config[line.split()[1]] = UnquotedStr(line.split(' ', 2)[2])
                if line.startswith('ejudge_remove_config'):
                    config.pop(line.split()[1])
        except:
            pass

        problem_exists = False
        for problem_cfg in contest_config.problems:
            if 'id' in problem_cfg and problem_cfg['id'] == ejudge_problem_id:
                problem_exists = True
                problem_cfg.update(config)

        if not problem_exists:
            contest_config.problems.append(config)

        problem_config.update(config)

        problem_cfg_file = open("problem.cfg", "w")
        print(PROBLEM_CFG_START, file=problem_cfg_file)
        Config.print_config(problem_config, problem_cfg_file)
        problem_cfg_file.close()
        contest_config.write()

    except Exception as e:
        os.chdir(contest_dir)
        #shutil.rmtree(problem_dir)
        old_contest_config.write()
        print("Failed to load problem")

        raise e


def import_problem(
        ejudge_contest_id: int,
        polygon_problem_id=None,
        src_path=None,
        short_name=None,
        ejudge_problem_id=None,
        no_offline=False,
) -> None:
    if src_path is not None:
        src_path = os.path.abspath(src_path)
        file_name = os.path.basename(src_path)
        file_name = file_name[:file_name.find('$')]
        file_name = file_name[:file_name.rfind('-')]
        src_dir = os.path.dirname(src_path)
        problem_zip_path = find_zip_and_move(file_name, src_dir)
    elif polygon_problem_id is not None:
        problem_zip_path = download_problem_package(polygon_problem_id)
    else:
        raise ValueError("Neither --src-path not --problem-id are specified")

    import_zip_problem(
        ejudge_contest_id=ejudge_contest_id,
        problem_zip_path=problem_zip_path,
        polygon_id=polygon_problem_id,
        short_name=short_name,
        ejudge_problem_id=ejudge_problem_id,
        no_offline=no_offline,
    )


def get_problems_polygon(
        polygon_id: int,
) -> None:
    cli_config.setup_login_by_url('')
    session = problem.ProblemSession(cli_config.polygon_url, None, None)
    problems = session.send_api_request('contest.problems', {'contestId': polygon_id}, problem_data=False)
    problem_keys = list(problems.keys())
    problem_keys.sort()

    problems_map = {}
    for key in problem_keys:
        problem_zip_path = download_problem_package(problems[key]['id'])
        yield key, problem_zip_path, problems[key]['id']


def find_zip_and_move(
        problem_name: str,
        src_dir: str
) -> str:
    problem_zip_name = None
    for package in os.listdir(src_dir):
        if package.startswith(problem_name):
            problem_zip_name = package
            break
        if problem_name == package:
            problem_zip_name = package
            break
        p = re.compile(f'{problem_name}-\d\$[a-z]*\.zip')
        if p.match(package) is not None:
            problem_zip_name = package
            break
    if problem_zip_name is None:
        raise ValueError(f"problem {problem_name} not found")

    tmp_dir = TMP_DOWNLOAD_DIR_PATTERN.format(suffix="local")

    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir)

    package_dst = os.path.join(tmp_dir, f"{problem_name}.zip")
    if os.path.exists(package_dst):
        os.remove(package_dst)

    shutil.copyfile(os.path.join(src_dir, problem_zip_name), package_dst)

    return package_dst


def get_problems_local(
        descriptor: str,
        src_dir: str,
) -> None:
    tree = ET.parse(descriptor)
    tree = tree.getroot()

    for problem in tree.find("problems"):
        key = problem.attrib["index"]
        problem_name = problem.attrib["url"].strip("/").split("/")[-1]

        problem_zip_path = find_zip_and_move(problem_name, src_dir)

        yield key, problem_zip_path, None


def import_contest(
        ejudge_id: int,
        polygon_id=None,
        descriptor=None,
        src_dir=None,
        no_offline=False,
) -> None:
    if descriptor is not None:
        if src_dir is None:
            raise ValueError("--descriptor is specified but --src-dir is not")
        descriptor = os.path.abspath(descriptor)
        src_dir = os.path.abspath(src_dir)
        problems = get_problems_local(descriptor, src_dir)
    elif polygon_id is not None:
        problems = get_problems_polygon(polygon_id)
    else:
        raise ValueError("Neither --descriptor nor --polygon-id are specified")

    for key, problem_zip_path, polygon_id in problems:
        import_zip_problem(
            ejudge_contest_id=ejudge_id,
            problem_zip_path=problem_zip_path,
            polygon_id=polygon_id,
            short_name=key,
            no_offline=no_offline,
        )


def add_subparsers(subparsers):
    parser_import_problem = subparsers.add_parser(
        'ip',
        help="Import single problem from polygon"
    )
    parser_import_problem.add_argument('contest_id', help='Id of ejudge contest to add problem', type=int)
    parser_import_problem.add_argument('-p', '--problem-id', help='Polygon id for the problem', default=None, type=int)
    parser_import_problem.add_argument('-s', '--src-path', help='Path to full zip package', default=None, type=str)
    parser_import_problem.add_argument('-short', help="Short name for the problem", default=None, type=str)
    parser_import_problem.add_argument('-ej_id', help="Ejudge id for the problem", default=None, type=int)
    parser_import_problem.add_argument('-n', "--no-offline", help="Ignore offline groups in valuer", action="store_true")
    parser_import_problem.set_defaults(
        func=lambda options: import_problem(options.contest_id, options.problem_id, options.src_path, options.short, options.ej_id, options.no_offline)
    )

    parser_import_contest = subparsers.add_parser(
        'ic',
        help="Import contest from polygon to ejudge"
    )
    parser_import_contest.add_argument('ejudge_id', help='Ejudge contest id', type=int)
    parser_import_contest.add_argument("-p", "--polygon-id", help='Polygon contest id', type=int)
    parser_import_contest.add_argument(
        "-d", "--descriptor",
        help='Path to contest descriptor(contest.xml)',
        default=None, type=str)
    parser_import_contest.add_argument(
        "-s", "--src-dir",
        help='Path to a directory with full problem zip packages, archive names should match problem names in Polygon',
        default=None, type=str)
    parser_import_contest.add_argument("-n", "--no-offline", help="Ignore offline groups in valuer", action="store_true")
    parser_import_contest.set_defaults(
        func=lambda options: import_contest(options.ejudge_id, options.polygon_id, options.descriptor, options.src_dir, options.no_offline)
    )
