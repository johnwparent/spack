# escape=`
FROM {{ bootstrap.image }} AS bootstrap


SHELL ["powershell", "-Command", "$ErrorActionPreference = 'Stop'; $ProgressPreference = 'Continue'; $verbosePreference='Continue';"]

# Enable use of 8.3filenames on image
# This is required to build multiple packages (or maybe just perl)
RUN fsutil 8dot3name set C:\ 0

# Install SSL certs from CA
RUN (certutil -generateSSTFromWU roots.sst) -AND (certutil -addstore -f root roots.sst) -AND (del roots.sst)

# Restore the default Windows shell for correct batch processing.
SHELL ["cmd", "/S", "/C"]

# Install build tools including MSVC, CMake, Win-SDK
RUN `
    curl -SL --output vs_community.exe https://aka.ms/vs/17/release/vs_community.exe `
    && start /w vs_community.exe --quiet --wait --norestart --nocache `
    --add Microsoft.VisualStudio.Product.Community `
    --add Microsoft.VisualStudio.Workload.NativeDesktop `
    --add Microsoft.VisualStudio.Component.Windows11SDK.22621 `
    --add Microsoft.VisualStudio.Component.Windows10SDK.20348 `
    --add Microsoft.VisualStudio.Component.TestTools.BuildTools `
    --add Microsoft.Component.VC.Runtime.UCRTSDK `
    && del /q vs_community.exe

RUN `
    curl -SL --output vs_community.exe https://aka.ms/vs/17/release/vs_community.exe `
    && start /w vs_community.exe modify --quiet --wait --norestart --nocache `
    --installPath "C:\Program Files\Microsoft Visual Studio\2022\Community"`
    --add Microsoft.VisualStudio.Workload.VCTools `
    --add Microsoft.VisualStudio.Component.VC.CLI.Support `
    --add Microsoft.VisualStudio.Component.VC.CMake.Project `
    --add Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
    --add Microsoft.VisualStudio.Component.VC.CLI.Support `
    --add Microsoft.VisualStudio.Component.VC.v141.x86.x64 `
    && del /q vs_community.exe

# download and install IntelOneAPI base toolkit (ifx) w/ msvc integration
ENV ONEAPI_FORTRAN_URL=https://registrationcenter-download.intel.com/akdlm/IRC_NAS/f6a44238-5cb6-4787-be83-2ef48bc70cba/w_fortran-compiler_p_2024.1.0.466_offline.exe
RUN `
    curl -SL --output oneapi_installer.exe %ONEAPI_FORTRAN_URL% `
    && start /w oneapi_installer.exe -s --remove-extracted-files yes -a --silent --eula accept`
    && del oneapi_installer.exe

ENV PYTHON_INSTALLER_URL=https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe
RUN `
    curl -SL --output python310_installer.exe %PYTHON_INSTALLER_URL% `
    && python310_installer.exe /quiet Include_debug=1 PrependPath=1 InstallAllUsers=1 `
    && del python310_installer.exe

# Install spack requirements
RUN python -m pip install --upgrade pip setuptools wheel
RUN python -m pip install pyreadline boto3 pyyaml pytz minio requests clingo pywin32 psutil

ENV GIT_INSTALLER_URL=https://github.com/git-for-windows/git/releases/download/v2.45.2.windows.1/Git-2.45.2-64-bit.exe
RUN ( `
echo [Setup] `
echo Lang=Default `
echo Dir=C:\Program Files ^(x86^)\Git `
echo Group=Git `
echo NoIcons=0 `
echo SetupType=default `
echo Components=gitlfs,assoc `
echo Tasks= `
echo PathOption=Cmd `
echo EnableSymlinks=Enabled `
echo EnableFSMonitor=Disabled `
echo CRLFOption=LFOnly `
)>git_options.ini
RUN `
    curl -SL --output git_installer.exe %GIT_INSTALLER_URL% `
    && git_installer.exe /VERYSILENT /NORESTART /NOCANCEL /SP- /LOADINF=git_options.ini `
    && del git_installer.exe 

{% block env_vars %}
ENV SPACK_ROOT=C:\spack `
    CURRENTLY_BUILDING_DOCKER_IMAGE=1 `
    container=docker
{% endblock %}

{% block install_os_packages %}
{% endblock %}

RUN mkdir %SPACK_ROOT% && cd %SPACK_ROOT% && `
    {{ bootstrap.spack_checkout }} && `
    mkdir %SPACK_ROOT%\opt\spack

{% block post_checkout %}
{% endblock %}

WORKDIR C:\\

SHELL [ "C:\spack\bin\spack_cmd.bat" ]


# Creates the package cache
RUN spack bootstrap now `
    && spack bootstrap status --optional `
    && spack spec hdf5+mpi

