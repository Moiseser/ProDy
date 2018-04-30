"""This module defines a class for handling ensembles of PDB conformations."""

from numbers import Integral
import numpy as np

from prody.sequence import MSA, Sequence
from prody.atomic import Atomic, AtomGroup
from prody.measure import getRMSD, getTransformation
from prody.utilities import checkCoords, checkWeights, copy
from prody import LOGGER

from .ensemble import Ensemble
from .conformation import PDBConformation

__all__ = ['PDBEnsemble']


class PDBEnsemble(Ensemble):

    """This class enables handling coordinates for heterogeneous structural
    datasets and stores identifiers for individual conformations.

    See usage usage in :ref:`pca-xray`, :ref:`pca-dimer`, and :ref:`pca-blast`.

    .. note:: This class is designed to handle conformations with missing
       coordinates, e.g. atoms that are note resolved in an X-ray structure.
       For unresolved atoms, the coordinates of the reference structure is
       assumed in RMSD calculations and superpositions."""

    def __init__(self, title='Unknown'):

        self._labels = []
        Ensemble.__init__(self, title)
        self._trans = None
        self._msa = None

    def __repr__(self):

        return '<PDB' + Ensemble.__repr__(self)[1:]

    def __str__(self):

        return 'PDB' + Ensemble.__str__(self)

    def __add__(self, other):
        """Concatenate two ensembles. The reference coordinates of *self* is
        used in the result."""

        if not isinstance(other, Ensemble):
            raise TypeError('an Ensemble instance cannot be added to an {0} '
                            'instance'.format(type(other)))
        elif self.numAtoms() != other.numAtoms():
            raise ValueError('Ensembles must have same number of atoms.')

        ensemble = PDBEnsemble('{0} + {1}'.format(self.getTitle(),
                                                  other.getTitle()))
        ensemble.setCoords(copy(self._coords))
        weights = copy(self._weights)
        if self._confs is not None:
            ensemble.addCoordset(copy(self._confs), weights=weights, 
                                 label=self.getLabels(), sequence=self._msa)
        
        other_weights = copy(other._weights)
        ensemble.addCoordset(copy(other._confs), weights=other_weights, 
                             label=other.getLabels(), sequence=other._msa)

        if self._atoms is not None:
            ensemble.setAtoms(self._atoms)
            ensemble._indices = self._indices
        else:
            ensemble.setAtoms(other._atoms)
            ensemble._indices = other._indices
        return ensemble

    def __iter__(self):

        n_confs = self._n_csets
        for i in range(n_confs):
            if n_confs != self._n_csets:
                raise RuntimeError('number of conformations in the ensemble '
                                   'changed during iteration')
            yield PDBConformation(self, i)

    def __getitem__(self, index):
        """Returns a conformation at given index."""

        msa = self._msa
        if msa:
            msa = self._msa[index]
        if isinstance(index, Integral):
            return self.getConformation(index)

        elif isinstance(index, slice):
            ens = PDBEnsemble('{0} ({1[0]}:{1[1]}:{1[2]})'.format(
                              self._title, index.indices(len(self))))
            ens.setCoords(copy(self._coords))
            
            ens.addCoordset(self._confs[index].copy(),
                            self._weights[index].copy(),
                            label=self._labels[index],
                            sequence=msa)
            if self._trans is not None:
                ens._trans = self._trans[index]
            ens.setAtoms(self._atoms)
            ens._indices = self._indices
            return ens

        elif isinstance(index, (list, np.ndarray)):
            ens = PDBEnsemble('{0}'.format(self._title))
            ens.setCoords(copy(self._coords))
            labels = list(np.array(self._labels)[index])
            ens.addCoordset(self._confs[index].copy(),
                            self._weights[index].copy(),
                            label=labels,
                            sequence=msa)
            if self._trans is not None:
                ens._trans = self._trans[index]
            ens.setAtoms(self._atoms)
            ens._indices = self._indices
            return ens
        else:
            raise IndexError('invalid index')

    def _superpose(self, **kwargs):
        """Superpose conformations and update coordinates."""

        calcT = getTransformation
        if kwargs.get('trans', False):
            if self._trans is not None:
                LOGGER.info('Existing transformations will be overwritten.')
            trans = np.zeros((self._n_csets, 4, 4))
        else:
            trans = None
        indices = self._indices
        if indices is None:
            weights = self._weights
            coords = self._coords
            confs = self._confs
            confs_selected = self._confs
        else:
            weights = self._weights[:, indices]
            coords = self._coords[indices]
            confs = self._confs
            confs_selected = self._confs[:, indices]

        for i, conf in enumerate(confs_selected):
            rmat, tvec = calcT(conf, coords, weights[i])
            if trans is not None:
                trans[i][:3, :3] = rmat
                trans[i][:3, 3] = tvec
            confs[i] = tvec + np.dot(confs[i], rmat.T)
        self._trans = trans

    def iterpose(self, rmsd=0.0001):

        confs = self._confs.copy()
        Ensemble.iterpose(self, rmsd)
        self._confs = confs
        LOGGER.info('Final superposition to calculate transformations.')
        self.superpose()

    iterpose.__doc__ = Ensemble.iterpose.__doc__

    def addCoordset(self, coords, weights=None, label=None, **kwargs):
        """Add coordinate set(s) to the ensemble.  *coords* must be a Numpy
        array with suitable shape and dimensionality, or an object with
        :meth:`getCoordsets`. *weights* is an optional argument.
        If provided, its length must match number of atoms.  Weights of
        missing (not resolved) atoms must be ``0`` and weights of those
        that are resolved can be anything greater than ``0``.  If not
        provided, weights of all atoms for this coordinate set will be
        set equal to ``1``. *label*, which may be a PDB identifier or a
        list of identifiers, is used to label conformations."""

        degeneracy = kwargs.pop('degeneracy', False)

        atoms = coords
        n_atoms = self.numAtoms()
        n_select = self.numSelected()
        n_confs = self.numCoordsets()

        try:
            if degeneracy:
                if self._coords is not None:
                    if isinstance(coords, Ensemble):
                        coords = coords._getCoords(selected=False)
                    elif hasattr(coords, '_getCoords'):
                        coords = coords._getCoords()
                else:
                    if isinstance(coords, Ensemble):
                        coords = coords.getCoords(selected=False)
                    elif hasattr(coords, 'getCoords'):
                        coords = coords.getCoords()
            else:
                if self._coords is not None:
                    if isinstance(coords, Ensemble):
                        coords = coords._getCoordsets(selected=False)
                    elif hasattr(coords, '_getCoordsets'):
                        coords = coords._getCoordsets()
                else:
                    if isinstance(coords, Ensemble):
                        coords = coords.getCoordsets(selected=False)
                    elif hasattr(coords, 'getCoordsets'):
                        coords = coords.getCoordsets()

        except AttributeError:
            label = label or 'Unknown'

        else:
            if coords is None:
                raise ValueError('coordinates are not set')
            elif label is None and isinstance(atoms, Atomic):
                if not isinstance(atoms, AtomGroup):
                    ag = atoms.getAtomGroup()
                else:
                    ag = atoms
                label = ag.getTitle()
                if coords.shape[0] < ag.numCoordsets():
                    label += '_m' + str(atoms.getACSIndex())
            else:
                label = label or 'Unknown'

        # check coordinates
        try:
            checkCoords(coords, csets=True, natoms=n_atoms)
        except:
            try:
                checkCoords(coords, csets=True, natoms=n_select)
            except TypeError:
                raise TypeError('coords must be a numpy array or an object '
                                'with `getCoords` method')

        if coords.ndim == 2:
            n_nodes, _ = coords.shape
            coords = coords.reshape((1, n_nodes, 3))
            n_csets = 1
        else:
            n_csets, n_nodes, _ = coords.shape
            if degeneracy:
                coords = coords[:1]

        n_repeats = 1 if degeneracy else n_csets
       
        if not n_atoms:
            self._n_atoms = n_nodes

        if n_nodes == n_select and self.isSelected():
            full_coords = np.repeat(self._coords[np.newaxis, :, :], n_csets, axis=0)
            full_coords[:, self._indices, :] = coords
            coords = full_coords
        
        # check weights
        if weights is None:
            weights = np.ones((n_csets, n_atoms, 1), dtype=float)
        else:
            weights = checkWeights(weights, n_atoms, n_csets)

        if degeneracy:
            weights = weights[:1]

        # check sequences
        seqs = None
        sequence = kwargs.pop('sequence', None)
        if hasattr(atoms, 'getSequence'):
            if sequence is not None:
                LOGGER.warn('sequence is supplied though coords has getSequence')
            sequence = atoms.getSequence()
            seqs = [sequence for _ in range(n_repeats)]
        else:
            if sequence is None:
                try:
                    sequence = self.getAtoms().getSequence()
                except AttributeError:
                    if self._msa:
                        sequence = ''.join('X' for _ in range(n_atoms))
                    # sequence and seqs remains to be None if MSA has not been created
            if isinstance(sequence, Sequence):
                seqs = [str(sequence)]
            elif isinstance(sequence, MSA):
                seqs = [str(seq) for seq in sequence]
            elif np.isscalar(sequence):
                seqs = [sequence for _ in range(n_repeats)]
        
        if seqs:
            if len(seqs) != n_repeats:
                raise ValueError('the number of sequences should be either one or '
                                'that of coordsets')

        # assign new values
        # update labels
        if n_csets > 1 and not degeneracy:
            if isinstance(label, str):
                labels = ['{0}_m{1}'.format(label, i+1) for i in range(n_csets)]
            else:
                if len(label) != n_csets:
                    raise ValueError('length of label and number of '
                                        'coordinate sets must be the same')
                labels = label
        else:
            labels = [label] if np.isscalar(label) else label

        self._labels.extend(labels)

        # update sequences
        if seqs:
            msa = MSA(seqs, title=self.getTitle(), labels=labels)
            if self._msa is None:
                if n_confs > 0:
                    def_seqs = np.chararray((n_confs, n_atoms))
                    def_seqs[:] = 'X'

                    old_labels = [self._labels[i] for i in range(n_confs)]
                    self._msa = MSA(def_seqs, title=self.getTitle(), labels=old_labels)
                    self._msa.extend(msa)
                else:
                    self._msa = msa
            else:
                self._msa.extend(msa)

        # update coordinates
        if self._confs is None and self._weights is None:
            self._confs = coords
            self._weights = weights
            self._n_csets = n_repeats
            
        elif self._confs is not None and self._weights is not None:
            self._confs = np.concatenate((self._confs, coords), axis=0)
            self._weights = np.concatenate((self._weights, weights), axis=0)
            self._n_csets += n_repeats
        else:
            raise RuntimeError('_confs and _weights must be set or None at '
                               'the same time')

    def getMSA(self, indices=None, selected=True):
        """Returns an MSA of selected atoms."""

        selected = selected and self._indices is not None
        if self._msa is None:
            return None
        
        atom_indices = self._indices if selected else slice(None, None, None)
        indices = indices if indices is not None else slice(None, None, None)
        
        return self._msa[indices, atom_indices]

    def getLabels(self):
        """Returns identifiers of the conformations in the ensemble."""

        return list(self._labels)

    def getCoordsets(self, indices=None, selected=True):
        """Returns a copy of coordinate set(s) at given *indices* for selected
        atoms. *indices* may be an integer, a list of integers or **None**.
        **None** returns all coordinate sets.

        .. warning:: When there are atoms with weights equal to zero (0),
           their coordinates will be replaced with the coordinates of the
           ensemble reference coordinate set."""

        if self._confs is None:
            return None

        if indices is None:
            indices = slice(None)
        else:
            indices = np.array([indices]).flatten()
        coords = self._coords
        if self._indices is None or not selected:
            confs = self._confs[indices].copy()
            for i, w in enumerate(self._weights[indices]):
                which = w.flatten() == 0
                confs[i, which] = coords[which]
        else:
            selids = self._indices
            coords = coords[selids]
            confs = self._confs[indices, selids].copy()
            for i, w in enumerate(self._weights[indices]):
                which = w[selids].flatten() == 0
                confs[i, which] = coords[which]
        return confs

    _getCoordsets = getCoordsets

    def iterCoordsets(self):
        """Iterate over coordinate sets. A copy of each coordinate set for
        selected atoms is returned. Reference coordinates are not included."""

        conf = PDBConformation(self, 0)
        for i in range(self._n_csets):
            conf._index = i
            yield conf.getCoords()

    def delCoordset(self, index):
        """Delete a coordinate set from the ensemble."""

        Ensemble.delCoordset(self, index)
        if isinstance(index, Integral):
            index = [index]
        else:
            index = list(index)
        index.sort(reverse=True)
        for i in index:
            self._labels.pop(i)

        if self._msa is not None:
            rest = []
            for i in range(self._msa.numSequences()):
                if i not in index:
                    rest.append(i)
            self._msa = self._msa[rest]

    def getConformation(self, index):
        """Returns conformation at given index."""

        if self._confs is None:
            raise AttributeError('conformations are not set')
        if not isinstance(index, Integral):
            raise TypeError('index must be an integer')
        n_confs = self._n_csets
        if -n_confs <= index < n_confs:
            if index < 0:
                index = n_confs + index
            return PDBConformation(self, index)
        else:
            raise IndexError('conformation index out of range')

    def getMSFs(self):
        """Calculate and return mean square fluctuations (MSFs).
        Note that you might need to align the conformations using
        :meth:`superpose` or :meth:`iterpose` before calculating MSFs."""

        if self._confs is None:
            return
        indices = self._indices
        if indices is None:
            coords = self._coords
            confs = self._confs
            weights = self._weights > 0
        else:
            coords = self._coords[indices]
            confs = self._confs[:, indices]
            weights = self._weights[:, indices] > 0
        weightsum = weights.sum(0)
        mean = np.zeros(coords.shape)
        for i, conf in enumerate(confs):
            mean += conf * weights[i]
        mean /= weightsum
        ssqf = np.zeros(mean.shape)
        for i, conf in enumerate(confs):
            ssqf += ((conf - mean) * weights[i]) ** 2
        return ssqf.sum(1) / weightsum.flatten()

    def getRMSDs(self, pairwise=False):
        """Calculate and return root mean square deviations (RMSDs). Note that
        you might need to align the conformations using :meth:`superpose` or
        :meth:`iterpose` before calculating RMSDs.

        :arg pairwise: if **True** then it will return pairwise RMSDs 
            as an n-by-n matrix. n is the number of conformations.
        :type pairwise: bool
        """

        if self._confs is None or self._coords is None:
            return None

        indices = self._indices
        if indices is None:
            indices = np.arange(self._confs.shape[1])

        weights = self._weights[:, indices] if self._weights is not None else None
        if pairwise:
            n_confs = self.numConfs()
            RMSDs = np.zeros((n_confs, n_confs))
            for i in range(n_confs):
                for j in range(i+1, n_confs):
                    if weights is None:
                        w = None
                    else:
                        wi = weights[i]; wj = weights[j]
                        w = wi * wj
                    RMSDs[i, j] = RMSDs[j, i] = getRMSD(self._confs[i, indices], self._confs[j, indices], w)
        else:
            RMSDs = getRMSD(self._coords[indices], self._confs[:, indices], weights)

        return RMSDs

    def setWeights(self, weights):
        """Set atomic weights."""

        if self._n_atoms == 0:
            raise AttributeError('coordinates are not set')

        try:
            self._weights = checkWeights(weights, self._n_atoms, self._n_csets)
        except ValueError:
            weights = checkWeights(weights, self.numSelected(), self._n_csets)
            if not self._weights:
                self._weights = np.ones((self._n_csets, self._n_atoms, 1), dtype=float)
            self._weights[self._indices, :] = weights    

