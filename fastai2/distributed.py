# AUTOGENERATED! DO NOT EDIT! File to edit: dev/20a_distributed.ipynb (unless otherwise specified).

__all__ = ['ParallelTrainer', 'setup_distrib', 'DistributedDL', 'DistributedTrainer']

# Cell
from .basics import *
from .callback.progress import ProgressCallback
from torch.nn.parallel import DistributedDataParallel, DataParallel
from torch.utils.data.distributed import DistributedSampler

# Cell
@patch
def reset(self: DataParallel):
    if hasattr(self.module, 'reset'): self.module.reset()

# Cell
class ParallelTrainer(Callback):
    run_after,run_before = TrainEvalCallback,Recorder
    def __init__(self, device_ids): self.device_ids = device_ids
    def begin_fit(self): self.learn.model = DataParallel(self.learn.model, device_ids=self.device_ids)
    def after_fit(self): self.learn.model = self.learn.model.module

# Cell
@patch
def to_parallel(self: Learner, device_ids=None):
    self.add_cb(ParallelTrainer(device_ids))
    return self

# Cell
@patch
def reset(self: DistributedDataParallel):
    if hasattr(self.module, 'reset'): self.module.reset()

# Cell
def setup_distrib(gpu=None):
    if gpu is None: return gpu
    gpu = int(gpu)
    torch.cuda.set_device(int(gpu))
    if num_distrib() > 1:
        torch.distributed.init_process_group(backend='nccl', init_method='env://')
    return gpu

# Cell
@delegates()
class DistributedDL(TfmdDL):

    def __init__(self, dataset, rank, world_size, **kwargs):
        super().__init__(dataset, **kwargs)
        if self.n%world_size != 0: self.n += world_size-self.n%world_size
        self.total_n,self.n = self.n,self.n//world_size
        store_attr(self, 'rank,world_size')

    def get_idxs(self):
        idxs = Inf.count if self.indexed else Inf.nones
        return idxs if self.n is None else list(itertools.islice(idxs, self.total_n))

    def shuffle_fn(self, idxs):
        "Deterministically shuffle on each training process based on epoch."
        g = torch.Generator()
        g.manual_seed(self.epoch)
        return L(idxs)[torch.randperm(self.total_n, generator=g)]

    def sample(self):
        idxs = self.get_idxs()
        if self.shuffle: idxs = self.shuffle_fn(idxs)
        # add extra samples to make it evenly divisible
        idxs += idxs[:(self.total_n - len(idxs))]
        # subsample
        idxs = idxs[self.rank:self.total_n:self.world_size]
        return (b for i,b in enumerate(idxs) if i//(self.bs or 1)%self.nw==self.offs)

    def create_item(self, s):
        if s is not None and s >= len(self.dataset): s = s%len(self.dataset)
        return super().create_item(s)

    def set_epoch(self, epoch): self.epoch = epoch

    @classmethod
    def from_dl(cls, dl, rank, world_size, **kwargs):
        cur_kwargs = dict(num_workers=dl.fake_l.num_workers, pin_memory=dl.pin_memory, timeout=dl.timeout,
                          bs=dl.bs, shuffle=dl.shuffle, drop_last=dl.drop_last, indexed=dl.indexed)
        cur_kwargs.update({n: getattr(dl, n) for n in cls._methods if n not in "get_idxs sample shuffle_fn create_item".split()})
        return cls(dl.dataset, rank, world_size, **merge(cur_kwargs, kwargs))

# Cell
class DistributedTrainer(Callback):
    run_after,run_before = TrainEvalCallback,Recorder
    def __init__(self, cuda_id=0): self.cuda_id = cuda_id

    def begin_fit(self):
        self.learn.model = DistributedDataParallel(self.model, device_ids=[self.cuda_id], output_device=self.cuda_id)
        self.old_dls = [dl for dl in self.dbunch.dls]
        self.learn.dbunch.dls = [self._wrap_dl(dl) for dl in self.dbunch.dls]
        if rank_distrib() > 0: self.learn.logger=noop

    def _wrap_dl(self, dl):
        return dl if isinstance(dl, DistributedDL) else DistributedDL.from_dl(dl, rank_distrib(), num_distrib())

    def begin_epoch(self):
        for dl in self.dbunch.dls: dl.set_epoch(self.epoch)

    def begin_train(self):    self.dl = self._wrap_dl(self.dl)
    def begin_validate(self): self.dl = self._wrap_dl(self.dl)

    def after_fit(self):
        self.learn.model = self.learn.model.module
        self.learn.dbunch.dls = self.old_dls

# Cell
@patch
def to_distributed(self: Learner, cuda_id):
    self.add_cb(DistributedTrainer(cuda_id))
    if rank_distrib() > 0: self.remove_cb(self.progress)
    return self