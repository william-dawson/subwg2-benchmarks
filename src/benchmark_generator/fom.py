"""Figure-of-merit calculations for completed mVMC and SALMON runs."""


def mvmc_get_size(infile):
    with open(infile) as ifile:
        W = L = Wsub = Lsub = None
        for line in ifile:
            split = line.split()
            if not split:
                continue
            if split[0] == "W":
                W = int(split[-1])
            elif split[0] == "L":
                L = int(split[-1])
            elif split[0] == "Wsub":
                Wsub = int(split[-1])
            elif split[0] == "Lsub":
                Lsub = int(split[-1])
    return W, L, Wsub, Lsub


def mvmc_get_time(tfile):
    with open(tfile) as ifile:
        for line in ifile:
            if "All" in line:
                return float(line.split()[-1])


def mvmc_fom(infile, tfile):
    """
    Calculate the figure of merit for a given mVMC run.

    Parameters:
        infile (str): Path to the mVMC .inp file.
        tfile (str): Path to the mVMC timing file (zvo_CalcTimer.dat).

    Returns:
        float: Time to solution divided by the scaling cost,
            [(Lsub*Wsub) * (L*W) + (L*W)]^3.
    """
    time = mvmc_get_time(tfile)
    W, L, Wsub, Lsub = mvmc_get_size(infile)
    work = ((Lsub * Wsub) * (L * W) + (L * W)) ** 3
    return time / work


def salmon_get_calc_time(fname):
    with open(fname) as ifile:
        for line in ifile:
            if "total calculation time" in line:
                return float(line.split(",")[1])


def salmon_get_nstates(fname):
    with open(fname) as ifile:
        for line in ifile:
            if "nstate" in line:
                return int(line.split()[-1])


def salmon_get_ngrid(fname):
    with open(fname) as ifile:
        for line in ifile:
            if "num_rgrid" in line:
                split = line.split()
                dim = [int(x.split(",")[0]) for x in split[2:]]
                return dim[0] * dim[1] * dim[2]


def salmon_fom(infile, gsfile, tdfile):
    """
    Calculate the figure of merit for a given SALMON run.

    Parameters:
        infile (str): Path to the SALMON ground-state .nml input file.
        gsfile (str): Path to the ground-state calculation output.
        tdfile (str): Path to the TDDFT calculation output.

    Returns:
        float: Total calculation time divided by (nstate * num_rgrid).
    """
    gstime = salmon_get_calc_time(gsfile)
    tdtime = salmon_get_calc_time(tdfile)
    total = gstime + tdtime

    states = salmon_get_nstates(infile)
    grid = salmon_get_ngrid(infile)

    return total / (states * grid)
