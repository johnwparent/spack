# escape=`
FROM {{ bootstrap.image }} AS bootstrap

SHELL ["cmd", "/S", "/C"]
{% block env_vars %}
ENV SPACK_ROOT=C:\spack `
    CURRENTLY_BUILDING_DOCKER_IMAGE=1 `
    container=docker
{% endblock %}

{% block install_os_packages %}
{% endblock %}

RUN mkdir $SPACK_ROOT && cd $SPACK_ROOT && `
    {{ bootstrap.spack_checkout }} && `
    mkdir $SPACK_ROOT\opt\spack

RUN ln -s $SPACK_ROOT\share\spack\docker\entrypoint.bash `
          \usr\local\bin\docker-shell `
 && ln -s $SPACK_ROOT\share\spack\docker\entrypoint.bash `
          \usr\local\bin\interactive-shell `
 && ln -s $SPACK_ROOT\share\spack\docker\entrypoint.bash `
          \usr\local\bin\spack-env


{% block post_checkout %}
{% endblock %}

WORKDIR C:\\
SHELL ["docker-shell"]

# Creates the package cache
RUN spack bootstrap now `
    && spack bootstrap status --optional `
    && spack spec hdf5+mpi

ENTRYPOINT ["\bin\bash", "\opt\spack\share\spack\docker\entrypoint.bash"]
CMD ["interactive-shell"]
