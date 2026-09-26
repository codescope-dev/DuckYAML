import glob
import os
import re

import yaml

INPUT_FILE = './input/application.yml'
OUTPUT_DIR = './output'

# Keys that scope a whole YAML document to one or more profiles. spring.profiles.active is deliberately
# not one of them: it *activates* profiles and is kept as a regular property.
PROFILE_DECLARATION_KEYS = ['spring.config.activate.on-profile', 'spring.profiles']
ACTIVATION_PREFIX = 'spring.config.activate.'
SIMPLE_PROFILE_NAME = re.compile(r'[\w.-]+')
DOCUMENT_SEPARATOR = '#---'
ESCAPES = {'\\': '\\\\', '\t': '\\t', '\n': '\\n', '\r': '\\r', '\f': '\\f'}


def format_scalar(value) -> str:
    """Render a YAML scalar the way Spring sees it: null is empty and booleans are lowercase."""
    if value is None:
        return ''
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def normalize_map(value, parent_key='') -> dict:
    """Flatten a YAML document into Spring property keys.

    Nested maps become dotted keys. Lists of scalars become comma separated values, and any other list
    (or one whose items contain commas) becomes indexed keys like ``servers[0].host``.
    """
    if isinstance(value, dict):
        if not value:
            return {parent_key: ''} if parent_key else {}
        items = {}
        for k, v in value.items():
            k = format_scalar(k)
            items.update(normalize_map(v, f'{parent_key}.{k}' if parent_key else k))
        return items
    if isinstance(value, list):
        if not value:
            return {parent_key: ''}
        if all(not isinstance(v, (dict, list)) and ',' not in format_scalar(v) for v in value):
            return {parent_key: ','.join(format_scalar(v) for v in value)}
        items = {}
        for i, v in enumerate(value):
            items.update(normalize_map(v, f'{parent_key}[{i}]'))
        return items
    return {parent_key: format_scalar(value)}


def pop_profiles(props: dict):
    """Remove the profile declaration from a flattened document and return its value, or None."""
    for base in PROFILE_DECLARATION_KEYS:
        pattern = re.compile(re.escape(base) + r'(\[\d+])?')
        keys = [k for k in props if pattern.fullmatch(k)]
        if keys:
            return ','.join(props.pop(k) for k in keys)
    return None


def escape(text: str, is_key=False) -> str:
    """Escape text for a .properties file. Non-ASCII characters become \\uXXXX so any file encoding works."""
    out = []
    for i, ch in enumerate(text):
        if ch in ESCAPES:
            out.append(ESCAPES[ch])
        elif (is_key and ch in '=: ') or (i == 0 and ch in ('#!' if is_key else ' ')):
            out.append('\\' + ch)
        elif not ' ' <= ch <= '~':
            utf16 = ch.encode('utf-16-be')
            out.extend(f'\\u{int.from_bytes(utf16[j:j + 2], "big"):04x}' for j in range(0, len(utf16), 2))
        else:
            out.append(ch)
    return ''.join(out)


def write_properties(path, documents):
    with open(path, 'w', encoding='utf-8') as file:
        for i, props in enumerate(documents):
            if i:
                file.write(DOCUMENT_SEPARATOR + '\n')
            for k, v in props.items():
                file.write(f'{escape(k, is_key=True)}={escape(v)}\n')


def main(input_file=INPUT_FILE, output_dir=OUTPUT_DIR):
    # delete properties files in output folder before running
    os.makedirs(output_dir, exist_ok=True)
    for path in glob.glob(os.path.join(output_dir, '*.properties')):
        os.remove(path)
    print('output directory cleaned')

    files = {}  # file name -> properties merged from every document that targets it
    conditional_documents = []  # documents that can only be expressed as '#---' sections of application.properties
    with open(input_file, mode='rt', encoding='utf-8') as file:
        for index, document in enumerate(yaml.safe_load_all(file), start=1):
            if document is None:
                continue
            if not isinstance(document, dict):
                raise ValueError(f'YAML document {index} in {input_file} is not a map')
            normalized_map = normalize_map(document)
            profiles = pop_profiles(normalized_map)
            names = [p.strip() for p in profiles.split(',') if p.strip()] if profiles is not None else []

            if any(k.startswith(ACTIVATION_PREFIX) for k in normalized_map) \
                    or not all(SIMPLE_PROFILE_NAME.fullmatch(name) for name in names):
                # profile expressions like 'prod & cloud' or other activation conditions have no
                # profile-specific file equivalent, so keep the condition in a multi-document section
                if profiles is not None:
                    normalized_map = {PROFILE_DECLARATION_KEYS[0]: profiles, **normalized_map}
                conditional_documents.append(normalized_map)
            else:
                # a list of profiles means "any of these", so the properties apply to each of them;
                # later documents override earlier ones, as in Spring
                for name in names or [None]:
                    new_file_name = f'application-{name}.properties' if name else 'application.properties'
                    files.setdefault(new_file_name, {}).update(normalized_map)

    if conditional_documents:
        files.setdefault('application.properties', {})
    for new_file_name, props in files.items():
        documents = [props, *conditional_documents] if new_file_name == 'application.properties' else [props]
        write_properties(os.path.join(output_dir, new_file_name), documents)
        print(f'created {new_file_name}')


if __name__ == '__main__':
    main()
