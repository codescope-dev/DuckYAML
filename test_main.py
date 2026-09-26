import os
import tempfile
import textwrap
import unittest

from main import main


class MainTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.input_file = os.path.join(self.tmp.name, 'application.yml')
        self.output_dir = os.path.join(self.tmp.name, 'output')

    def convert(self, yml):
        with open(self.input_file, 'w', encoding='utf-8') as file:
            file.write(textwrap.dedent(yml))
        main(self.input_file, self.output_dir)
        outputs = {}
        for name in sorted(os.listdir(self.output_dir)):
            with open(os.path.join(self.output_dir, name), encoding='utf-8') as file:
                outputs[name] = file.read()
        return outputs

    def test_profiles_active_is_a_regular_property(self):
        self.assertEqual(self.convert('''
            spring:
              profiles:
                active: dev
            server:
              port: 8080
        '''), {'application.properties': 'spring.profiles.active=dev\nserver.port=8080\n'})

    def test_profile_documents(self):
        self.assertEqual(self.convert('''
            name: base
            ---
            spring:
              config:
                activate:
                  on-profile: prod
            name: prod
            ---
            spring:
              profiles: test
            name: test
        '''), {
            'application.properties': 'name=base\n',
            'application-prod.properties': 'name=prod\n',
            'application-test.properties': 'name=test\n',
        })

    def test_documents_for_the_same_profile_are_merged(self):
        self.assertEqual(self.convert('''
            a: 1
            ---
            b: 2
            ---
            spring.config.activate.on-profile: prod
            a: 1
            b: 2
            ---
            spring.config.activate.on-profile: prod
            b: 3
            c: 4
        '''), {
            'application.properties': 'a=1\nb=2\n',
            'application-prod.properties': 'a=1\nb=3\nc=4\n',
        })

    def test_profile_list_applies_to_each_profile(self):
        self.assertEqual(self.convert('''
            spring.config.activate.on-profile: localstack, dev
            a: 1
            ---
            spring.config.activate.on-profile: [qa, uat]
            b: 2
        '''), {
            'application-localstack.properties': 'a=1\n',
            'application-dev.properties': 'a=1\n',
            'application-qa.properties': 'b=2\n',
            'application-uat.properties': 'b=2\n',
        })

    def test_conditions_without_a_profile_file_become_documents(self):
        self.assertEqual(self.convert('''
            a: 1
            ---
            spring.config.activate.on-profile: prod & cloud
            b: 2
            ---
            spring.config.activate.on-cloud-platform: kubernetes
            c: 3
        '''), {'application.properties': textwrap.dedent('''\
            a=1
            #---
            spring.config.activate.on-profile=prod & cloud
            b=2
            #---
            spring.config.activate.on-cloud-platform=kubernetes
            c=3
        ''')})

    def test_scalars_are_formatted_like_spring(self):
        self.assertEqual(self.convert('''
            enabled: true
            banner-mode: off
            empty:
            empty-map: {}
            empty-list: []
            port: 8080
            404: not-found
        '''), {'application.properties': textwrap.dedent('''\
            enabled=true
            banner-mode=false
            empty=
            empty-map=
            empty-list=
            port=8080
            404=not-found
        ''')})

    def test_values_and_keys_are_escaped(self):
        self.assertEqual(self.convert(r'''
            path: 'C:\temp'
            text: |
              line1
              line2
            padded: '  x'
            unicode: café
            map:
              "a=b: c": 1
              "#x": 2
        '''), {'application.properties': textwrap.dedent(r'''
            path=C:\\temp
            text=line1\nline2\n
            padded=\  x
            unicode=caf\u00e9
            map.a\=b\:\ c=1
            map.#x=2
        ''').lstrip()})

    def test_lists(self):
        self.assertEqual(self.convert('''
            servers: [a.com, b.com]
            ports: [80, 443]
            commas: ['a,b', c]
            nested:
              - host: a
                port: 1
              - [x, y]
        '''), {'application.properties': textwrap.dedent('''\
            servers=a.com,b.com
            ports=80,443
            commas[0]=a,b
            commas[1]=c
            nested[0].host=a
            nested[0].port=1
            nested[1]=x,y
        ''')})

    def test_empty_documents_are_skipped(self):
        self.assertEqual(self.convert('---\na: 1\n---\n'), {'application.properties': 'a=1\n'})

    def test_stale_output_is_removed(self):
        os.makedirs(self.output_dir)
        with open(os.path.join(self.output_dir, 'application-old.properties'), 'w'):
            pass
        self.assertEqual(self.convert('a: 1\n'), {'application.properties': 'a=1\n'})


if __name__ == '__main__':
    unittest.main()
