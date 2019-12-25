# AUTOGENERATED! DO NOT EDIT! File to edit: dev/06_data.block.ipynb (unless otherwise specified).

__all__ = ['TransformBlock', 'CategoryBlock', 'MultiCategoryBlock', 'DataBlock']

# Cell
from ..torch_basics import *
from .core import *
from .load import *
from .external import *
from .transforms import *

# Cell
class TransformBlock():
    "A basic wrapper that links defaults transforms for the data block API"
    def __init__(self, type_tfms=None, item_tfms=None, batch_tfms=None, dl_type=None, dbunch_kwargs=None):
        self.type_tfms  =            L(type_tfms)
        self.item_tfms  = ToTensor + L(item_tfms)
        self.batch_tfms = Cuda     + L(batch_tfms)
        self.dl_type,self.dbunch_kwargs = dl_type,({} if dbunch_kwargs is None else dbunch_kwargs)

# Cell
def CategoryBlock(vocab=None, add_na=False):
    "`TransformBlock` for single-label categorical targets"
    return TransformBlock(type_tfms=Categorize(vocab=vocab, add_na=add_na))

# Cell
def MultiCategoryBlock(encoded=False, vocab=None, add_na=False):
    "`TransformBlock` for multi-label categorical targets"
    tfm = EncodedMultiCategorize(vocab=vocab) if encoded else [MultiCategorize(vocab=vocab, add_na=add_na), OneHotEncode]
    return TransformBlock(type_tfms=tfm)

# Cell
from inspect import isfunction,ismethod

# Cell
def _merge_tfms(*tfms):
    "Group the `tfms` in a single list, removing duplicates (from the same class) and instantiating"
    g = groupby(concat(*tfms), lambda o:
        o if isinstance(o, type) else o.__qualname__ if (isfunction(o) or ismethod(o)) else o.__class__)
    return L(v[-1] for k,v in g.items()).map(instantiate)

# Cell
@docs
@funcs_kwargs
class DataBlock():
    "Generic container to quickly build `DataSource` and `DataBunch`"
    get_x=get_items=splitter=get_y = None
    dl_type = TfmdDL
    _methods = 'get_items splitter get_y get_x'.split()
    def __init__(self, blocks=None, dl_type=None, getters=None, n_inp=None, **kwargs):
        blocks = L(getattr(self,'blocks',(TransformBlock,TransformBlock)) if blocks is None else blocks)
        blocks = L(b() if callable(b) else b for b in blocks)
        self.default_type_tfms = blocks.attrgot('type_tfms', L())
        self.default_item_tfms  = _merge_tfms(*blocks.attrgot('item_tfms',  L()))
        self.default_batch_tfms = _merge_tfms(*blocks.attrgot('batch_tfms', L()))
        for t in blocks:
            if getattr(t, 'dl_type', None) is not None: self.dl_type = t.dl_type
        if dl_type is not None: self.dl_type = dl_type
        self.databunch = delegates(self.dl_type.__init__)(self.databunch)
        self.dbunch_kwargs = merge(*blocks.attrgot('dbunch_kwargs', {}))
        self.n_inp,self.getters = n_inp,L(getters)
        if getters is not None: assert self.get_x is None and self.get_y is None
        assert not kwargs

    def datasource(self, source, type_tfms=None):
        self.source = source
        items = (self.get_items or noop)(source)
        if isinstance(items,tuple):
            items = L(items).zip()
            labellers = [itemgetter(i) for i in range_of(self.default_type_tfms)]
        else: labellers = [noop] * len(self.default_type_tfms)
        splits = (self.splitter or noop)(items)
        if self.get_x:   labellers[0] = self.get_x
        if self.get_y:   labellers[1] = self.get_y
        if self.getters: labellers = self.getters
        if type_tfms is None: type_tfms = [L() for t in self.default_type_tfms]
        type_tfms = L([self.default_type_tfms, type_tfms, labellers]).map_zip(
            lambda tt,tfm,l: L(l) + _merge_tfms(tt, tfm))
        return DataSource(items, tfms=type_tfms, splits=splits, dl_type=self.dl_type, n_inp=self.n_inp)

    def databunch(self, source, path='.', type_tfms=None, item_tfms=None, batch_tfms=None, **kwargs):
        dsrc = self.datasource(source, type_tfms=type_tfms)
        item_tfms  = _merge_tfms(self.default_item_tfms,  item_tfms)
        batch_tfms = _merge_tfms(self.default_batch_tfms, batch_tfms)
        kwargs = {**self.dbunch_kwargs, **kwargs}
        return dsrc.databunch(path=path, after_item=item_tfms, after_batch=batch_tfms, **kwargs)

    _docs = dict(datasource="Create a `Datasource` from `source` with `type_tfms`",
                 databunch="Create a `DataBunch` from `source` with `item_tfms` and `batch_tfms`")