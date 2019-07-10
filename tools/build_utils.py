#!/usr/bin/env python3
# ==============================================================================
#  Copyright 2019 Intel Corporation
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# ==============================================================================

import argparse
from argparse import RawTextHelpFormatter

import errno
import os
import subprocess
from subprocess import check_output, call, Popen, PIPE
import sys
import shutil
import glob
import platform
import shlex
import grp, pwd


def get_tf_cxxabi():
    import tensorflow as tf
    print('Version information:')
    print('TensorFlow version: ', tf.__version__)
    print('C Compiler version used in building TensorFlow: ',
          tf.__compiler_version__)
    return str(tf.__cxx11_abi_flag__)


def is_venv():
    # https://stackoverflow.com/questions/1871549/determine-if-python-is-running-inside-virtualenv
    return (hasattr(sys, 'real_prefix') or
            (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix))


def command_executor(cmd, verbose=False, msg=None, stdout=None, stderr=None):
    '''
    Executes the command.
    Example: 
      - command_executor('ls -lrt')
      - command_executor(['ls', '-lrt'])
    '''
    if type(cmd) == type([]):  # if its a list, convert to string
        cmd = ' '.join(cmd)
    if verbose:
        tag = 'Running COMMAND: ' if msg is None else msg
        print(tag + cmd)
    if (call(shlex.split(cmd), stdout=stdout, stderr=stderr) != 0):
        raise Exception("Error running command: " + cmd)


def build_ngraph(build_dir, src_location, cmake_flags, verbose):
    pwd = os.getcwd()

    src_location = os.path.abspath(src_location)
    print("Source location: " + src_location)

    os.chdir(src_location)

    # mkdir build directory
    path = build_dir
    try:
        os.makedirs(path)
    except OSError as exc:  # Python >2.5
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass

    # Run cmake
    os.chdir(build_dir)

    cmake_cmd = ["cmake"]
    cmake_cmd.extend(cmake_flags)
    cmake_cmd.extend([src_location])

    command_executor(cmake_cmd, verbose=True)

    import psutil
    num_cores = str(psutil.cpu_count(logical=True))
    cmd = ["make", "-j" + num_cores]
    if verbose:
        cmd.extend(['VERBOSE=1'])
    command_executor(cmd, verbose=True)
    cmd = ["make", "install"]
    command_executor(cmd, verbose=True)

    os.chdir(pwd)


def install_virtual_env(venv_dir):
    # Check if we have virtual environment
    # TODO

    # Setup virtual environment
    venv_dir = os.path.abspath(venv_dir)
    # Note: We assume that we are using Python 3 (as this script is also being
    # executed under Python 3 as marked in line 1)
    command_executor(["virtualenv", "-p", "python3", venv_dir])


def load_venv(venv_dir):
    venv_dir = os.path.abspath(venv_dir)

    # Check if we are already inside the virtual environment
    # return (hasattr(sys, 'real_prefix')
    #         or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix))
    print("Loading virtual environment from: %s" % venv_dir)

    activate_this_file = venv_dir + "/bin/activate_this.py"
    # The execfile API is for Python 2. We keep here just in case you are on an
    # obscure system without Python 3
    # execfile(activate_this_file, dict(__file__=activate_this_file))
    exec(
        compile(
            open(activate_this_file, "rb").read(), activate_this_file, 'exec'),
        dict(__file__=activate_this_file), dict(__file__=activate_this_file))

    return venv_dir


def get_exitcode_stdout_stderr(cmd):
    """
    Execute the external command and get its exitcode, stdout and stderr.
    """
    args = shlex.split(cmd)

    proc = Popen(args, stdout=PIPE, stderr=PIPE)
    out, err = proc.communicate()
    exitcode = proc.returncode
    #
    return exitcode, out, err


def setup_venv(venv_dir):
    load_venv(venv_dir)

    print("PIP location")
    call(['which', 'pip'])

    # Patch the MacOS pip to avoid the TLS issue
    if (platform.system() == 'Darwin'):
        get_pip = open("get-pip.py", "wb")
        call([
            "curl",
            "https://bootstrap.pypa.io/get-pip.py",
        ], stdout=get_pip)
        call(["python3", "./get-pip.py"])

    # Install the pip packages
    cmdpart = ["pip"]
    if os.getenv("IN_DOCKER") != None:
        cmdpart.append("--cache-dir=" + os.getcwd())
    package_list = [
        "install",
        "-U",
        "pip",
        "setuptools",
        "psutil",
        "six>=1.10.0",
        "numpy>=1.13.3",
        "absl-py>=0.1.6",
        "astor>=0.6.0",
        "google_pasta>=0.1.1",
        "wheel>=0.26",
        "mock",
        "termcolor>=1.1.0",
        "protobuf>=3.6.1",
        "keras_applications>=1.0.6",
        "--no-deps",
        "keras_preprocessing==1.0.5",
        "--no-deps",
        "yapf==0.26.0",
    ]
    cmd = cmdpart + package_list
    command_executor(cmd)

    # Print the current packages
    cmd = ["pip", "list"]
    if os.getenv("IN_DOCKER") != None:
        cmd.append("--cache-dir=" + os.getcwd())
    command_executor(cmd)


def build_tensorflow(venv_dir, src_dir, artifacts_dir, target_arch, verbosity):
    base = sys.prefix
    python_lib_path = os.path.join(base, 'lib', 'python%s' % sys.version[:3],
                                   'site-packages')
    python_executable = os.path.join(base, "bin", "python")

    print("PYTHON_BIN_PATH: " + python_executable)

    # In order to build TensorFlow, we need to be in the virtual environment
    pwd = os.getcwd()

    src_dir = os.path.abspath(src_dir)
    print("SOURCE DIR: " + src_dir)

    # Update the artifacts directory
    artifacts_dir = os.path.join(os.path.abspath(artifacts_dir), "tensorflow")
    print("ARTIFACTS DIR: %s" % artifacts_dir)

    os.chdir(src_dir)

    # Set the TensorFlow configuration related variables
    os.environ["PYTHON_BIN_PATH"] = python_executable
    os.environ["PYTHON_LIB_PATH"] = python_lib_path
    os.environ["TF_NEED_IGNITE"] = "0"
    if (platform.system() == 'Darwin'):
        os.environ["TF_ENABLE_XLA"] = "0"
        os.environ["TF_CONFIGURE_IOS"] = "0"
    else:
        os.environ["TF_ENABLE_XLA"] = "1"
    os.environ["TF_NEED_OPENCL_SYCL"] = "0"
    os.environ["TF_NEED_COMPUTECPP"] = "0"
    os.environ["TF_NEED_ROCM"] = "0"
    os.environ["TF_NEED_MPI"] = "0"
    os.environ["TF_NEED_CUDA"] = "0"
    os.environ["TF_DOWNLOAD_CLANG"] = "0"
    os.environ["TF_SET_ANDROID_WORKSPACE"] = "0"
    os.environ["CC_OPT_FLAGS"] = "-march=" + target_arch

    command_executor("./configure")

    # Build the python package
    cmd = [
        "bazel",
        "build",
        "--config=opt",
        "--config=noaws",
        "--config=nohdfs",
        "--config=noignite",
        "--config=nokafka",
        "--config=nonccl",
        "//tensorflow/tools/pip_package:build_pip_package",
    ]
    if verbosity:
        cmd.extend(['-s'])

    command_executor(cmd)

    command_executor([
        "bazel-bin/tensorflow/tools/pip_package/build_pip_package",
        artifacts_dir
    ])

    # Get the name of the TensorFlow pip package
    tf_wheel_files = glob.glob(os.path.join(artifacts_dir, "tensorflow-*.whl"))
    print("TF Wheel: %s" % tf_wheel_files[0])

    # popd
    os.chdir(pwd)


def build_tensorflow_cc(src_dir, artifacts_dir, target_arch, verbosity):
    pwd = os.getcwd()

    base = sys.prefix
    python_lib_path = os.path.join(base, 'lib', 'python%s' % sys.version[:3],
                                   'site-packages')
    python_executable = os.path.join(base, "bin", "python")

    print("PYTHON_BIN_PATH: " + python_executable)

    src_dir = os.path.abspath(src_dir)
    print("SOURCE DIR: " + src_dir)

    # Update the artifacts directory
    artifacts_dir = os.path.join(os.path.abspath(artifacts_dir), "tensorflow")
    print("ARTIFACTS DIR: %s" % artifacts_dir)

    os.chdir(src_dir)

    # Set the TensorFlow configuration related variables
    os.environ["PYTHON_BIN_PATH"] = python_executable
    os.environ["PYTHON_LIB_PATH"] = python_lib_path
    os.environ["TF_NEED_IGNITE"] = "0"
    if (platform.system() == 'Darwin'):
        os.environ["TF_ENABLE_XLA"] = "0"
        os.environ["TF_CONFIGURE_IOS"] = "0"
    else:
        os.environ["TF_ENABLE_XLA"] = "1"
    os.environ["TF_NEED_OPENCL_SYCL"] = "0"
    os.environ["TF_NEED_COMPUTECPP"] = "0"
    os.environ["TF_NEED_ROCM"] = "0"
    os.environ["TF_NEED_MPI"] = "0"
    os.environ["TF_NEED_CUDA"] = "0"
    os.environ["TF_DOWNLOAD_CLANG"] = "0"
    os.environ["TF_SET_ANDROID_WORKSPACE"] = "0"
    os.environ["CC_OPT_FLAGS"] = "-march=" + target_arch

    command_executor("./configure")

    # Now build the TensorFlow C++ library
    cmd = [
        "bazel", "build", "--config=opt", "--config=noaws", "--config=nohdfs",
        "--config=noignite", "--config=nokafka", "--config=nonccl",
        "//tensorflow:libtensorflow_cc.so.1"
    ]
    command_executor(cmd)
    copy_tf_cc_lib_to_artifacts(artifacts_dir, None)

    # popd
    os.chdir(pwd)


def copy_tf_cc_lib_to_artifacts(artifacts_dir, tf_prebuilt):
    tf_cc_lib_name = 'libtensorflow_cc.so.1'
    # if (platform.system() == 'Darwin'):
    # tf_cc_lib_name = 'libtensorflow_cc.1.dylib'
    try:
        doomed_file = os.path.join(artifacts_dir, tf_cc_lib_name)
        os.unlink(doomed_file)
    except OSError:
        print("Cannot remove: %s" % doomed_file)
        pass

    # Now copy the TF libraries
    if tf_prebuilt is None:
        tf_cc_lib_file = "bazel-bin/tensorflow/" + tf_cc_lib_name
    else:
        tf_cc_lib_file = os.path.abspath(tf_prebuilt + '/' + tf_cc_lib_name)

    print("Copying %s to %s" % (tf_cc_lib_file, artifacts_dir))
    shutil.copy(tf_cc_lib_file, artifacts_dir)


def locate_tf_whl(tf_whl_loc):
    possible_whl = [i for i in os.listdir(tf_whl_loc) if '.whl' in i]
    assert len(possible_whl
              ) == 1, "Expected 1 TF whl file, but found " + len(possible_whl)
    tf_whl = os.path.abspath(tf_whl_loc + '/' + possible_whl[0])
    assert os.path.isfile(tf_whl), "Did not find " + tf_whl
    return tf_whl


def copy_tf_to_artifacts(artifacts_dir, tf_prebuilt):
    tf_fmwk_lib_name = 'libtensorflow_framework.so.1'
    if (platform.system() == 'Darwin'):
        tf_fmwk_lib_name = 'libtensorflow_framework.1.dylib'
    try:
        doomed_file = os.path.join(artifacts_dir, "libtensorflow_cc.so.1")
        os.unlink(doomed_file)
        doomed_file = os.path.join(artifacts_dir, tf_fmwk_lib_name)
        os.unlink(doomed_file)
    except OSError:
        print("Cannot remove: %s" % doomed_file)
        pass

    # Now copy the TF libraries
    if tf_prebuilt is None:
        tf_cc_lib_file = "bazel-bin/tensorflow/libtensorflow_cc.so.1"
        tf_cc_fmwk_file = "bazel-bin/tensorflow/" + tf_fmwk_lib_name
    else:
        tf_cc_lib_file = os.path.abspath(tf_prebuilt + '/libtensorflow_cc.so.1')
        tf_cc_fmwk_file = os.path.abspath(tf_prebuilt + '/' + tf_fmwk_lib_name)
    print("PWD: ", os.getcwd())
    print("Copying %s to %s" % (tf_cc_lib_file, artifacts_dir))
    shutil.copy(tf_cc_lib_file, artifacts_dir)

    print("Copying %s to %s" % (tf_cc_fmwk_file, artifacts_dir))
    shutil.copy(tf_cc_fmwk_file, artifacts_dir)

    if tf_prebuilt is not None:
        tf_whl = locate_tf_whl(tf_prebuilt)
        shutil.copy(tf_whl, artifacts_dir)


def install_tensorflow(venv_dir, artifacts_dir):
    # Load the virtual env
    load_venv(venv_dir)

    # Install tensorflow pip
    tf_pip = os.path.join(os.path.abspath(artifacts_dir), "tensorflow")

    pwd = os.getcwd()
    os.chdir(os.path.join(artifacts_dir, "tensorflow"))

    # Get the name of the TensorFlow pip package
    tf_wheel_files = glob.glob("tensorflow-*.whl")
    if (len(tf_wheel_files) != 1):
        raise Exception(
            "artifacts directory contains more than 1 version of tensorflow wheel"
        )

    cmdpart = ["pip"]
    if os.getenv("IN_DOCKER") != None:
        cmdpart.append("--cache-dir=" + pwd)
    cmd = cmdpart + ["install", "-U", tf_wheel_files[0]]
    command_executor(cmd)

    cxx_abi = "0"
    if (platform.system() == 'Linux'):
        import tensorflow as tf
        cxx_abi = tf.__cxx11_abi_flag__
        print("LIB: %s" % tf.sysconfig.get_lib())
        print("CXX_ABI: %d" % cxx_abi)

    # popd
    os.chdir(pwd)

    return str(cxx_abi)


def build_ngraph_tf(build_dir, artifacts_location, ngtf_src_loc, venv_dir,
                    cmake_flags, verbose):
    pwd = os.getcwd()

    # Load the virtual env
    load_venv(venv_dir)

    cmdpart = ["pip"]
    if os.getenv("IN_DOCKER") != None:
        cmdpart.append("--cache-dir=" + pwd)
    cmd = cmdpart + ["list"]
    command_executor(cmd)

    # Get the absolute path for the artifacts
    artifacts_location = os.path.abspath(artifacts_location)

    ngtf_src_loc = os.path.abspath(ngtf_src_loc)
    print("Source location: " + ngtf_src_loc)

    os.chdir(ngtf_src_loc)

    # mkdir build directory
    path = build_dir
    try:
        os.makedirs(path)
    except OSError as exc:  # Python >2.5
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass

    # Run cmake
    os.chdir(path)
    cmake_cmd = ["cmake"]
    cmake_cmd.extend(cmake_flags)
    cmake_cmd.extend([ngtf_src_loc])
    command_executor(cmake_cmd)

    import psutil
    num_cores = str(psutil.cpu_count(logical=True))
    make_cmd = ["make", "-j" + num_cores, "install"]
    if verbose:
        make_cmd.extend(['VERBOSE=1'])

    command_executor(make_cmd)

    os.chdir(os.path.join("python", "dist"))
    ngtf_wheel_files = glob.glob("ngraph_tensorflow_bridge-*.whl")
    if (len(ngtf_wheel_files) != 1):
        print("Multiple Python whl files exist. Please remove old wheels")
        for whl in ngtf_wheel_files:
            print("Existing Wheel: " + whl)
        raise Exception("Error getting the ngraph-tf wheel file")

    output_wheel = ngtf_wheel_files[0]
    print("OUTPUT WHL FILE: %s" % output_wheel)

    output_path = os.path.join(artifacts_location, output_wheel)
    print("OUTPUT WHL DST: %s" % output_path)
    # Delete just in case it exists
    try:
        os.remove(output_path)
    except OSError:
        pass

    # Now copy
    shutil.copy2(output_wheel, artifacts_location)

    os.chdir(pwd)
    return output_wheel


def install_ngraph_tf(venv_dir, ngtf_pip_whl):
    # Load the virtual env
    load_venv(venv_dir)

    cmdpart = ["pip"]
    if os.getenv("IN_DOCKER") != None:
        cmdpart.append("--cache-dir=" + os.getcwd())
    cmd = cmdpart + ["install", "-U", ngtf_pip_whl]
    command_executor(cmd)

    import tensorflow as tf
    print('\033[1;34mVersion information\033[0m')
    print('TensorFlow version: ', tf.__version__)
    print('C Compiler version used in building TensorFlow: ',
          tf.__compiler_version__)
    import ngraph_bridge
    print(ngraph_bridge.__version__)


def download_repo(target_name, repo, version):
    # First download to a temp folder
    call(["git", "clone", repo, target_name])

    # Next goto this folder nd determine the name of the root folder
    pwd = os.getcwd()

    # Go to the tree
    os.chdir(target_name)

    # checkout the specified branch
    call(["git", "fetch"])
    command_executor(["git", "checkout", version])

    # Get the latest if applicable
    call(["git", "pull"])
    os.chdir(pwd)


def apply_patch(patch_file):
    cmd = subprocess.Popen(
        'patch -p1 -N -i ' + patch_file, shell=True, stdout=subprocess.PIPE)
    printed_lines = cmd.communicate()
    # Check if the patch is being applied for the first time, in which case
    # cmd.returncode will be 0 or if the patch has already been applied, in
    # which case the string will be found, in all other cases the assertion
    # will fail
    assert cmd.returncode == 0 or 'patch detected!  Skipping patch' in str(
        printed_lines[0]), "Error applying the patch."


def has_group(user, group_name):
    if os.getenv("USER") != None:
        user = os.getenv("USER")
        groups = [g.gr_name for g in grp.getgrall() if user in g.gr_mem]
        gid = pwd.getpwnam(user).pw_gid
        groups.append(grp.getgrgid(gid).gr_name)
    return groups.filter(name=group_name).exists()


def build_base(args):
    if os.getenv("USER") != None:
        user = os.getenv("USER")
        if has_group(user, "docker") == False:
            command_executor(["sudo", "usermod", "-aG", "docker", user])
            command_executor(["newgrp", "docker"])
    cmd = ["docker", "build", "--tag", "ngtf", "."]
    command_executor(cmd)


def start_container(workingdir):
    pwd = os.getcwd()
    u = os.getuid()
    g = os.getgid()
    cachedir = ".cache/bazel"
    parentdir = os.path.dirname(cachedir)
    abscachedir = os.path.abspath(cachedir)
    if os.path.isdir(abscachedir) == False:
        os.makedirs(abscachedir)
    start = [
        "docker", "run", "--name", "ngtf", "-u",
        str(u) + ":" + str(g), "-v", pwd + ":/ngtf", "-v", pwd + "/tf:/tf",
        "-v", pwd + "/" + parentdir + ":/bazel/" + parentdir, "-v",
        "/etc/passwd:/etc/passwd", "-w", workingdir, "-d", "-t", "ngtf"
    ]
    try:
        command_executor(
            start, stdout=open(os.devnull, "w"), stderr=open(os.devnull, "w"))
    except Exception as exc:
        msg = str(exc)
        print("caught exception: " + msg)


def check_container():
    exitcode, out, err = get_exitcode_stdout_stderr(
        "docker inspect -f '{{.State.Running}}' ngtf")
    if exitcode == 0:
        return True
    return False


def stop_container():
    try:
        stop = ["docker", "stop", "ngtf"]
        command_executor(
            stop, stdout=open(os.devnull, "w"), stderr=open(os.devnull, "w"))
        rm = ["docker", "rm", "ngtf"]
        command_executor(
            rm, stdout=open(os.devnull, "w"), stderr=open(os.devnull, "w"))
    except Exception as exc:
        msg = str(exc)
        print("caught exception: " + msg)


def run_in_docker(buildcmd, args):
    pwd = os.getcwd()
    u = os.getuid()
    g = os.getgid()
    proxy = ""
    if "ALL_PROXY" in os.environ:
        proxy += "-eALL_PROXY=" + os.environ["ALL_PROXY"]
    if "http_proxy" in os.environ:
        proxy += " -ehttp_proxy=" + os.environ["http_proxy"]
    if "HTTP_PROXY" in os.environ:
        proxy += " -eHTTP_PROXY" + os.environ["HTTP_PROXY"]
    if "https_proxy" in os.environ:
        proxy += " -e https_proxy=" + os.environ["https_proxy"]
    if "HTTPS_PROXY" in os.environ:
        proxy += " -e HTTPS_PROXY=" + os.environ["HTTPS_PROXY"]
    cmd = [
        "docker", "exec", proxy, "-e"
        "IN_DOCKER=true", "-e", "USER=" + os.getlogin(), "-e",
        "TEST_TMPDIR=/bazel/.cache/bazel", "-u",
        str(u) + ":" + str(g), "ngtf"
    ]
    vargs = vars(args)
    for arg in vargs:
        if arg not in ["run_in_docker", "build_base", "stop_container"]:
            if arg == "use_tensorflow_from_location":
                if vargs[arg] != '':
                    buildcmd += " --" + arg + "=/" + str(vargs[arg])
            elif vargs[arg] in [False, None]:
                pass
            elif vargs[arg] == True:
                buildcmd += " --" + arg
            else:
                buildcmd += " --" + arg + "=" + str(vargs[arg])
    cmd.append(buildcmd)
    verbose = False
    if 'verbose_build' in vargs:
        verbose = True
    command_executor(cmd, verbose=verbose)


def get_gcc_version():
    cmd = subprocess.Popen(
        'gcc -dumpversion',
        shell=True,
        stdout=subprocess.PIPE,
        bufsize=1,
        universal_newlines=True)
    output = cmd.communicate()[0].rstrip()
    return output


def get_cmake_version():
    cmd = subprocess.Popen(
        'cmake --version',
        shell=True,
        stdout=subprocess.PIPE,
        bufsize=1,
        universal_newlines=True)
    output = cmd.communicate()[0].rstrip()
    # The cmake version format is: "cmake version a.b.c"
    version_tuple = output.split()[2].split('.')
    return version_tuple


def get_bazel_version():
    cmd = subprocess.Popen(
        'bazel version',
        shell=True,
        stdout=subprocess.PIPE,
        bufsize=1,
        universal_newlines=True)
    # The bazel version format is a multi line output:
    #
    # Build label: 0.24.1
    # Build target: bazel-out/k8-opt/bin/src/main/java/com/...
    # Build time: Tue Apr 2 16:29:26 2019 (1554222566)
    # Build timestamp: 1554222566
    # Build timestamp as int: 1554222566
    #
    output = cmd.communicate()[0].splitlines()[0].strip()
    output = output.split(':')[1].strip()

    version_tuple = output.split('.')
    return version_tuple
