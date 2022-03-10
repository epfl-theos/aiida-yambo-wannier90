#! /usr/bin/env python3
"""Functions to process kmesh."""
import typing as ty

import numpy as np

from aiida import orm
from aiida.engine import calcfunction


@calcfunction
def get_output_explicit_kpoints(retrieved: orm.FolderData) -> orm.KpointsData:
    """Parse the kpoints in the stdout of a ``PwCalculation``.

    :param retrieved: the retrieved folder of a ``PwCalculation``.
    :type retrieved: orm.FolderData
    :return: an explicit list of kpoints in the stdout, in crystal coordinates.
    :rtype: orm.KpointsData
    """
    from aiida_quantumespresso.calculations.pw import PwCalculation

    from aiida_yambo_wannier90.parsers import parse_pw_output_kpoints

    if not isinstance(retrieved, orm.FolderData):
        raise ValueError(f"{retrieved} is not a FolderData")

    creator = retrieved.creator
    if not isinstance(creator, orm.CalcJobNode):
        raise ValueError(f"{creator} is not a CalcJobNode")

    if creator.process_class != PwCalculation:
        raise ValueError(f"{creator} is not a PwCalculation")

    output_filename = creator.attributes["output_filename"]
    output = retrieved.get_object_content(output_filename)
    kpoint_list = parse_pw_output_kpoints(output)

    kpoints = orm.KpointsData()
    kpoints.set_kpoints(kpoint_list)

    return kpoints


@calcfunction
def kmapper(
    dense_mesh: orm.KpointsData,
    coarse_mesh: orm.KpointsData,
    start_band: orm.Int,
    end_band: orm.Int,
) -> orm.List:
    """Find the mapping between kpoints in coarse mesh and a dense mesh.

    Given a coarse uniform kpoints grid needed to get MLWF (e.g. 4x4x4, full BZ),
    find the corresponding indeces into the, typically much denser, kpoints grid
    needed to convergence the self-energy (e.g. 12x12x12, reduced BZ).

    The input meshes must be commensurate, although the dense mesh can be
    a symmetry reduced mesh on IBZ.

    :param dense_mesh: usually a ``calc.outputs.output_band`` representing a pw.x
    symmetry-reduced grid in an IBZ but with larger density.
    :type dense_mesh: orm.KpointsData
    :param coarse_mesh: usually a ``KpointsData`` representing a uniform grid
    generated by ``wannier90/kmesh.pl``.
    :type coarse_mesh: orm.KpointsData
    :param start_band: index of start band for yambo to compute QP correction
    :type start_band: orm.Int
    :param end_band: index of end band for yambo to compute QP correction
    :type end_band: orm.Int
    :return: The ``QPkrange`` for yambo, i.e. a list of ``kpoint|kpoint|start_band|end_band``
    :rtype: orm.List
    """
    coarse_mesh = coarse_mesh.get_kpoints()
    dense_mesh = dense_mesh.get_kpoints()

    opt = np.array([0, 1, -1])
    k_list = []
    for i in coarse_mesh:
        count = 1
        for j in dense_mesh:
            q = i - j
            q = np.around(q, decimals=5)
            if q[0] in opt and q[1] in opt and q[2] in opt:
                k_list.append(count)
            count = count + 1

    qpkrange = [(_, _, start_band.value, end_band.value) for _ in k_list]

    return orm.List(list=qpkrange)


def find_commensurate_integers(  # pylint: disable=too-many-locals,import-outside-toplevel,too-many-branches,too-many-statements
    dense: int,
    coarse: int,
    *,
    include_identical: bool = True,
    debug_plot: bool = False,
) -> ty.Tuple[int, int]:
    """Increase the two integers to make the ``corase`` a divisor of ``dense``.

    Return the minimum possible solution, i.e. the smallest increment of the two
    integers to be commensurate.

    :param dense: the larger integer
    :type dense: int
    :param coarse: the smaller integer, however upon input it can be larger than
    the input ``dense`` integer, but upon output ``coarse`` is always smaller or
    equal than ``dense``.
    :type coarse: int
    :param debug_plot: dense = coarse is valid solution, otherwise dense always > coarse
    :type debug_plot: bool
    :param debug_plot: use matplotlib to plot all the solutions
    ```
    find_commensurate_integers(5, 2, debug_plot=True)
    find_commensurate_integers(11, 5, debug_plot=True)
    find_commensurate_integers(3, 5, debug_plot=True)
    ```
    :type debug_plot: bool
    :return: the new ``(dense, corase)`` integers that are commensurate.
    :rtype: ty.Tuple[int, int]
    """
    import math

    if debug_plot:
        import matplotlib.pyplot as plt
        from matplotlib.ticker import MultipleLocator

        _, ax = plt.subplots()
        ax.set_title("find_commensurate_integers")
        ax.set_xlabel("coarse")
        ax.set_ylabel("dense")
        ax.axis("equal")
        ax.grid(True)
        # use integer as ticks
        # ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        # ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        # this locator puts ticks at regular intervals
        ax.xaxis.set_major_locator(MultipleLocator(base=1))
        ax.yaxis.set_major_locator(MultipleLocator(base=1))

        # initial inputs, dense as y, coarse as x
        ax.scatter(coarse, dense, color="blue", label="input")

    # if dense if smaller or equal to coarse
    if dense <= coarse:
        if include_identical:
            solution = (coarse, coarse)
        else:
            return find_commensurate_integers(
                coarse + 1,
                coarse,
                include_identical=False,
                debug_plot=debug_plot,
            )

        if debug_plot:
            ax.scatter(*reversed(solution), color="red", label="solution")

            ax.legend()
            plt.autoscale(axis="both")
            plt.show()

        return solution

    # if dense is larger than coarse
    k = dense / coarse
    # klow = math.floor(k)
    # min of klow is 1 instead of the ratio
    klow = 1
    khigh = math.ceil(k)

    if debug_plot:
        ax.axline([0, 0], [1, klow], color="orange", label=r"$k_{low}$")
        ax.axline([0, 0], [1, khigh], color="orange", label=r"$k_{high}$")

    valid_solutions = []

    # two always good solutions
    new_dense = coarse * khigh
    solution = (new_dense, coarse)
    valid_solutions.append(solution)
    #
    if include_identical:
        solution = (dense, dense)
        valid_solutions.append(solution)

    # find all possible solutions
    for new_dense in range(dense, coarse * khigh):
        if include_identical:
            lim = new_dense // klow + 1
        else:
            lim = new_dense // klow
        for new_coarse in range(coarse, lim):
            mod = new_dense % new_coarse
            if mod == 0:
                solution = (new_dense, new_coarse)
                valid_solutions.append(solution)

    # find the minimal increment
    # we have two scaling numbers representing the cost of increasing the two meshes,
    # should be the scaling of yambo and wannier workflows, respectively.
    scaling_dense = 1.0
    scaling_coarse = 1.0

    # not sure if this is good, but use power law scaling at the moment.
    costs = [_[0] ** scaling_dense + _[1] ** scaling_coarse for _ in valid_solutions]
    idx = np.argmin(costs)

    solution = valid_solutions[idx]

    if debug_plot:
        x = [_[1] for _ in valid_solutions]
        y = [_[0] for _ in valid_solutions]
        ax.scatter(x, y, color="grey", label="valid solutions")
        ax.scatter(*reversed(solution), color="red", label="solution")

        ax.legend()
        plt.autoscale(axis="both")
        plt.show()

    return solution


@calcfunction
def find_commensurate_meshes(
    dense_mesh: orm.KpointsData, coarse_mesh: orm.KpointsData
) -> ty.Tuple[orm.KpointsData, orm.KpointsData]:
    """Find commensurate dense and coarse kmeshes.

    The dense mesh should be integer multiples of coarse mesh for each kx, ky, kz directions.
    Usually the input dense mesh is Yambo converged mesh, the input coarse mesh is the wannier90 mesh.
    The function tries to expand a bit the coarse or/and dense mesh to make them commensurate.
    Then the ``kmapper`` could find the mapping between coarse and dense meshes.

    The input dense mesh can be smaller than the coarse mesh, but the returned dense mesh is always
    larger or equal to the coarse mesh.

    :param dense_mesh: the dense mesh, the ``orm.KpointsData`` can be an explicit list or a mesh.
    :type dense_mesh: orm.KpointsData
    :param coarse_mesh: the coarse mesh, the ``orm.KpointsData`` can be an explicit list or a mesh.
    :type coarse_mesh: orm.KpointsData
    :return: the commensurate dense and coarse mesh.
    :rtype: ty.Tuple[orm.KpointsData, orm.KpointsData]
    """
    from aiida_wannier90_workflows.utils.kpoints import get_mesh_from_kpoints

    dense = get_mesh_from_kpoints(dense_mesh)
    coarse = get_mesh_from_kpoints(coarse_mesh)

    new_dense = [0, 0, 0]
    new_coarse = [0, 0, 0]

    for i in range(3):
        new_dense[i], new_coarse[i] = find_commensurate_integers(
            dense[i],
            coarse[i],
        )

    new_dense_mesh = orm.KpointsData()
    new_dense_mesh.set_kpoints_mesh(mesh=new_dense)

    new_coarse_mesh = orm.KpointsData()
    new_coarse_mesh.set_kpoints_mesh(mesh=new_coarse)

    return {"dense_mesh": new_dense_mesh, "coarse_mesh": new_coarse_mesh}
