###############################
import openbabel as ob
import pybel
import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem
###############################

def average_properties(mol):
    """
    Calculate all relevant properties for a given molecule averaged across conformers

    :param mol: input molecule
    :type mol: openbabel.OBMol
    :return: dictionary of properties
    :rtype dict

    ..todo: remove reliance on pybel
    """
    mols = run_confab(mol)
    num_confs = mols.NumConformers()

    globs = np.empty(num_confs)
    pbfs = np.empty(num_confs)
    for i in range(num_confs):
        mols.SetConformer(i)
        pymol = pybel.Molecule(mols)
        # calculate properties
        globs[i] = calc_glob(pymol)
        pbfs[i] = calc_pbf(pymol)

    data = {
        'form': pymol.formula,
        'molwt': pymol.molwt,
        'rb': rotatable_bonds(pymol),
        'glob': np.mean(globs),
        'pbf': np.mean(pbfs)
    }
    return data


def smiles_to_ob(mol_string):
    """
    Reads a SMILES string and creates a molecule object

    Currently, an initial guess at 3D geometry is performed by RDkit.

    :param mol_string: SMILES string
    :type mol_string: str
    :return: molecule object
    :rtype: openbabel.OBMol
    """
    mol = initial_geom_guess(mol_string)
    obmol = ob.OBMol()
    obConv = ob.OBConversion()
    obConv.SetInAndOutFormats("mol", "mol")
    obConv.ReadString(obmol, mol)
    return obmol


def initial_geom_guess(smiles):
    """
    Parses a SMILES string and performs an initial guess of geometry

    :param smiles: SMILES structure string
    :return: String with Mol structure text
    :rtype: str

    ..todo: use openbabel for initial guess
    """
    m = Chem.MolFromSmiles(smiles)
    m2 = Chem.AddHs(m)

    # Generate initial guess
    AllChem.EmbedMolecule(m2, AllChem.ETKDG())
    AllChem.MMFFOptimizeMolecule(m2)

    # Write mol file
    return Chem.MolToMolBlock(m2)


def run_confab(mol, rmsd_cutoff=0.5, conf_cutoff=100000, energy_cutoff=50.0, confab_verbose=False):
    """
    Generate ensemble of conformers to perform calculations on

    :param mol: initial molecule to generate conformers from
    :param rmsd_cutoff: similarity threshold for conformers, default: 0.5
    :param conf_cutoff: max number of conformers to generate, default: 100,000
    :param energy_cutoff: max relative energy between conformers, default: 50
    :param confab_verbose: whether confab should report on rotors
    :type mol: openbabel.OBMol
    :type rmsd_cutoff: float
    :type conf_cutoff: int
    :type energy_cutoff: float
    :type confab_verbose: bool
    :return: list of conformers for a given molecule
    :rtype: openbabel.OBMol
    """
    pff = ob.OBForceField_FindType( "mmff94" )
    pff.Setup(mol)

    pff.DiverseConfGen(rmsd_cutoff, conf_cutoff, energy_cutoff, confab_verbose)

    pff.GetConformers(mol);

    return mol

def calc_glob(mol):
    """
    Calculates the globularity (glob) of a molecule

    glob varies from 0 to 1 with completely flat molecules like benzene having a
    glob of 0 and spherical molecules like adamantane having a glob of 1

    :param mol: pybel molecule object
    :type mol: pybel.Molecule
    :return: globularity of molecule
    :rtype: float | int
    """
    points = get_atom_coords(mol, heavy_only = False)
    if points is None:
        return 0
    points = points.T

    # calculate covariance matrix
    cov_mat = np.cov([points[0,:],points[1,:],points[2,:]])

    # calculate eigenvalues of covariance matrix and sort
    vals, vecs = np.linalg.eig(cov_mat)
    vals = np.sort(vals)[::-1]

    # glob is ratio of last eigenvalue and first eigenvalue
    if vals[0] != 0:
        return vals[-1]/vals[0]
    else:
        return -1


def calc_pbf(mol):
    """
    Uses SVD to fit atoms in molecule to a plane then calculates the average
    distance to that plane.

    :param mol: pybel molecule object
    :type mol: pybel.Molecule
    :return: average distance of all atoms to the best fit plane
    :rtype: float
    """
    points = get_atom_coords(mol)
    c, n = svd_fit(points)
    pbf = calc_avg_dist(points, c, n)
    return pbf


def rotatable_bonds(mol):
    """
    Calculates the number of rotatable bonds in a molecules. Rotors are defined
    as any non-terminal bond between heavy atoms, excluding amides

    :param mol: pybel molecule object
    :type mol: pybel.Molecule
    :return rb: number of rotatable bonds
    :rtype int
    """
    rb = 0
    for bond in ob.OBMolBondIter(mol.OBMol):
        if bond.IsRotor() and not bond.IsAmide():
            rb += 1
    return rb


def calc_avg_dist(points, C, N):
    """
    Calculates the average distance a given set of points is from a plane

    :param points: numpy array of points
    :param C: centroid vector of plane
    :param N: normal vector of plane
    :return Average distance of each atom from the best-fit plane
    """
    sum = 0
    for xyz in points:
        sum += abs(distance(xyz, C, N))
    return sum / len(points)

def get_atom_coords(mol, heavy_only = False):
    """
    Retrieve the 3D coordinates of all atoms in a molecules

    :param mol: pybel molecule object
    :return numpy array of coordinates
    """
    num_atoms = len(mol.atoms)
    pts = np.empty(shape = (num_atoms,3))

    for a in range(num_atoms):
        pts[a] = mol.atoms[a].coords

    return pts

def svd_fit(X):
    """
    Fitting algorithmn was obtained from https://gist.github.com/lambdalisue/7201028
    Find (n - 1) dimensional standard (e.g. line in 2 dimension, plane in 3
    dimension, hyperplane in n dimension) via solving Singular Value
    Decomposition.
    The idea was explained in the following references
    - http://www.caves.org/section/commelect/DUSI/openmag/pdf/SphereFitting.pdf
    - http://www.geometrictools.com/Documentation/LeastSquaresFitting.pdf
    - http://www.ime.unicamp.br/~marianar/MI602/material%20extra/svd-regression-analysis.pdf

    :Example:
        >>> XY = [[0, 1], [3, 3]]
        >>> XY = np.array(XY)
        >>> C, N = svd_fit(XY)
        >>> C
        array([ 1.5,  2. ])
        >>> N
        array([-0.5547002 ,  0.83205029])

    :param X:n x m dimensional matrix which n indicate the number of the dimension and m indicate the number of points
    :return [C, N] where C is a centroid vector and N is a normal vector
    :rtype tuple
    """
    # Find the average of points (centroid) along the columns
    C = np.average(X, axis=0)
    # Create CX vector (centroid to point) matrix
    CX = X - C
    # Singular value decomposition
    U, S, V = np.linalg.svd(CX)
    # The last row of V matrix indicate the eigenvectors of
    # smallest eigenvalues (singular values).
    N = V[-1]
    return C, N


def distance(x, C, N):
    """
    Calculate an orthogonal distance between the points and the standard
    Args:
    :param x: n x m dimensional matrix
    :param C: n dimensional vector whicn indicate the centroid of the standard
    :param N: n dimensional vector which indicate the normal vector of the standard
    :return m dimensional vector which indicate the orthogonal distance. the value
            will be negative if the points beside opposite side of the normal vector
    """
    return np.dot(x - C, N)