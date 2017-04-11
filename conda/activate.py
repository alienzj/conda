# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals

from glob import glob
import os
from os.path import basename, dirname, isdir, join
import re
import sys

try:
    from cytoolz.itertoolz import concatv
except ImportError:
    from ._vendor.toolz.itertoolz import concatv  # NOQA

on_win = bool(sys.platform == "win32")
PY2 = sys.version_info[0] == 2
if PY2:  # pragma: py3 no cover
    def iteritems(d, **kw):
        return d.iteritems(**kw)
else:
    def iteritems(d, **kw):
        return iter(d.items(**kw))

# Need to answer 3 questions.
#  1. what is the new state of all environment variables?
#  2. what scripts do I need to run?
#  3. what prompt should I prepend?

# Strategy is to use the Activator class, where all core logic is is build_activate()
# or build_deactivate().  Each returns a map containing the keys: set_vars, unset_var,
# activate_scripts, deactivate_scripts.

class Activator(object):

    def __init__(self, shell):
        from .base.context import context
        self.context = context

        if shell == 'posix':
            self.pathsep = os.pathsep
            self.path_convert = lambda path: path
            self.script_extension = '.sh'

            self.unset_var_tmpl = 'unset %s'
            self.set_var_tmpl = 'export %s="%s"'
            self.run_script_tmpl = 'source %s'

        else:
            raise NotImplementedError()

    def activate(self, name_or_prefix):
        return '\n'.join(self._make_commands(self.build_activate(name_or_prefix)))

    def deactivate(self):
        return '\n'.join(self._make_commands(self.build_deactivate()))

    def _default_env(self, prefix):
        if prefix == self.context.root_prefix:
            return 'root'
        return basename(prefix) if basename(dirname(prefix)) == 'envs' else prefix

    def build_activate(self, name_or_prefix):
        from ._vendor.auxlib.path import expand
        from .base.context import locate_prefix_by_name
        if isdir(expand(name_or_prefix)):
            prefix = name_or_prefix
        elif re.search(r'\\|/', name_or_prefix):
            prefix = name_or_prefix
        else:
            prefix = locate_prefix_by_name(self.context, name_or_prefix)
        conda_default_env = self._default_env(prefix)

        old_conda_shlvl = int(os.getenv('CONDA_SHLVL', 0))
        old_conda_prefix = os.getenv('CONDA_PREFIX')
        old_path = os.environ['PATH']

        activate_scripts = glob(join(
            prefix, 'etc', 'conda', 'activate.d', '*' + self.script_extension
        ))

        if old_conda_shlvl == 0:
            set_vars = {
                'CONDA_PYTHON_PATH': sys.executable,
                'PATH': self._add_prefix_to_path(old_path, prefix),
                'CONDA_PREFIX': prefix,
                'CONDA_SHLVL': old_conda_shlvl + 1,
                'CONDA_DEFAULT_ENV': conda_default_env,
                'CONDA_PROMPT_MODIFIER': "(%s) " % conda_default_env if self.context.changeps1 else "",
            }
            deactivate_scripts = ()
        elif old_conda_shlvl == 1:
            set_vars = {
                'PATH': self._add_prefix_to_path(old_path, prefix),
                'CONDA_PREFIX': prefix,
                'CONDA_PREFIX_%d' % old_conda_shlvl: old_conda_prefix,
                'CONDA_SHLVL': old_conda_shlvl + 1,
                'CONDA_DEFAULT_ENV': conda_default_env,
                'CONDA_PROMPT_MODIFIER': "(%s) " % conda_default_env if self.context.changeps1 else "",
            }
            deactivate_scripts = ()
        elif old_conda_shlvl == 2:
            new_path = self._replace_prefix_in_path(old_path, old_conda_prefix, prefix)
            set_vars = {
                'PATH': new_path,
                'CONDA_PREFIX': prefix,
                'CONDA_DEFAULT_ENV': conda_default_env,
                'CONDA_PROMPT_MODIFIER': "(%s) " % conda_default_env if self.context.changeps1 else "",
            }
            deactivate_scripts = glob(join(
                old_conda_prefix, 'etc', 'conda', 'deactivate.d', '*' + self.script_extension
            ))
        else:
            raise NotImplementedError()

        return {
            'set_vars': set_vars,
            'deactivate_scripts': deactivate_scripts,
            'activate_scripts': activate_scripts,
        }

    def build_deactivate(self):
        old_conda_shlvl = int(os.getenv('CONDA_SHLVL', 0))
        new_conda_shlvl = old_conda_shlvl - 1
        old_conda_prefix = os.environ['CONDA_PREFIX']
        new_path = self._remove_prefix_from_path(os.environ['PATH'], old_conda_prefix)
        deactivate_scripts = glob(join(
            old_conda_prefix, 'etc', 'conda', 'deactivate.d', '*' + self.script_extension
        ))

        if old_conda_shlvl == 1:
            # TODO: warn conda floor
            unset_vars = (
                'CONDA_SHLVL',
                'CONDA_PREFIX',
                'CONDA_DEFAULT_ENV',
                'CONDA_PYTHON_PATH',
                'CONDA_PROMPT_MODIFIER',
            )
            set_vars = {
                'PATH': new_path,
            }
        elif old_conda_shlvl == 2:
            new_prefix = os.getenv('CONDA_PREFIX_%d' % new_conda_shlvl)
            conda_default_env = self._default_env(new_prefix)
            unset_vars = (
                'CONDA_PREFIX_%d' % new_conda_shlvl,
            )
            set_vars = {
                'PATH': new_path,
                'CONDA_SHLVL': new_conda_shlvl,
                'CONDA_PREFIX': new_prefix,
                'CONDA_DEFAULT_ENV': conda_default_env,
                'CONDA_PROMPT_MODIFIER': "(%s) " % conda_default_env if self.context.changeps1 else "",
            }
        else:
            raise NotImplementedError()

        return {
            'unset_vars': unset_vars,
            'set_vars': set_vars,
            'deactivate_scripts': deactivate_scripts,
        }

    def build_reactivate(self):
        conda_prefix = os.environ['CONDA_PREFIX']
        deactivate_scripts = glob(join(
            conda_prefix, 'etc', 'conda', 'deactivate.d', '*' + self.script_extension
        ))
        activate_scripts = glob(join(
            conda_prefix, 'etc', 'conda', 'activate.d', '*' + self.script_extension
        ))
        return {
            'deactivate_scripts': deactivate_scripts,
            'activate_scripts': activate_scripts,
        }

    def _get_path_dirs(self, prefix):
        _path_convert = self.path_convert
        if on_win:
            yield _path_convert(prefix.rstrip("\\"))
            yield _path_convert(join(prefix, 'Library', 'mingw-w64', 'bin'))
            yield _path_convert(join(prefix, 'Library', 'usr', 'bin'))
            yield _path_convert(join(prefix, 'Library', 'bin'))
            yield _path_convert(join(prefix, 'Scripts'))
        else:
            yield _path_convert(join(prefix, 'bin'))

    def _add_prefix_to_path(self, old_path, prefix):
        return self.pathsep.join(concatv(
            self._get_path_dirs(prefix),
            (old_path,),
        ))

    def _remove_prefix_from_path(self, current_path, prefix):
        _prefix_paths = re.escape(self.pathsep.join(self._get_path_dirs(prefix)))
        return re.sub(_prefix_paths, r'', current_path, 1)

    def _replace_prefix_in_path(self, current_path, old_prefix, new_prefix):
        _old_prefix_paths = re.escape(self.pathsep.join(self._get_path_dirs(old_prefix)))
        _new_prefix_paths = re.escape(self.pathsep.join(self._get_path_dirs(new_prefix)))
        return re.sub(_old_prefix_paths, _new_prefix_paths, current_path, 1)

    def _make_commands(self, cmds_dict):
        for key in cmds_dict.get('unset_vars', ()):
            yield self.unset_var_tmpl % key

        for key, value in iteritems(cmds_dict.get('set_vars', {})):
            yield self.set_var_tmpl % (key, value)

        for script in cmds_dict.get('deactivate_scripts', ()):
            yield self.run_script_tmpl % script

        for script in cmds_dict.get('activate_scripts', ()):
            yield self.run_script_tmpl % script


if __name__ == '__main__':
    command = sys.argv[1]
    shell = sys.argv[2]
    activator = Activator(shell)
    if command == 'activate':
        name_or_prefix = sys.argv[3]
        print(activator.activate(name_or_prefix))
    elif command == 'deactivate':
        print(activator.deactivate())
    elif command == 'reactivate':
        print(activator.reactivate())
    else:
        raise NotImplementedError()
