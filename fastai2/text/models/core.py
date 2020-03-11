# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/33_text.models.core.ipynb (unless otherwise specified).

__all__ = ['LinearDecoder', 'SequentialRNN', 'get_language_model', 'SentenceEncoder', 'masked_concat_pool',
           'PoolingLinearClassifier', 'get_text_classifier']

# Cell
from ...data.all import *
from ..core import *
from .awdlstm import *

# Cell
_model_meta = {AWD_LSTM: {'hid_name':'emb_sz', 'url':URLs.WT103_FWD, 'url_bwd':URLs.WT103_BWD,
                          'config_lm':awd_lstm_lm_config, 'split_lm': awd_lstm_lm_split,
                          'config_clas':awd_lstm_clas_config, 'split_clas': awd_lstm_clas_split},
               AWD_QRNN: {'hid_name':'emb_sz',
                          'config_lm':awd_qrnn_lm_config, 'split_lm': awd_lstm_lm_split,
                          'config_clas':awd_qrnn_clas_config, 'split_clas': awd_lstm_clas_split},}
              # Transformer: {'hid_name':'d_model', 'url':URLs.OPENAI_TRANSFORMER,
              #               'config_lm':tfmer_lm_config, 'split_lm': tfmer_lm_split,
              #               'config_clas':tfmer_clas_config, 'split_clas': tfmer_clas_split},
              # TransformerXL: {'hid_name':'d_model',
              #                'config_lm':tfmerXL_lm_config, 'split_lm': tfmerXL_lm_split,
              #                'config_clas':tfmerXL_clas_config, 'split_clas': tfmerXL_clas_split}}

# Cell
class LinearDecoder(Module):
    "To go on top of a RNNCore module and create a Language Model."
    initrange=0.1

    def __init__(self, n_out, n_hid, output_p=0.1, tie_encoder=None, bias=True):
        self.decoder = nn.Linear(n_hid, n_out, bias=bias)
        self.decoder.weight.data.uniform_(-self.initrange, self.initrange)
        self.output_dp = RNNDropout(output_p)
        if bias: self.decoder.bias.data.zero_()
        if tie_encoder: self.decoder.weight = tie_encoder.weight

    def forward(self, input):
        dp_inp = self.output_dp(input)
        return self.decoder(dp_inp), input, dp_inp

# Cell
class SequentialRNN(nn.Sequential):
    "A sequential module that passes the reset call to its children."
    def reset(self):
        for c in self.children(): getattr(c, 'reset', noop)()

# Cell
def get_language_model(arch, vocab_sz, config=None, drop_mult=1.):
    "Create a language model from `arch` and its `config`."
    meta = _model_meta[arch]
    config = ifnone(config, meta['config_lm']).copy()
    for k in config.keys():
        if k.endswith('_p'): config[k] *= drop_mult
    tie_weights,output_p,out_bias = map(config.pop, ['tie_weights', 'output_p', 'out_bias'])
    init = config.pop('init') if 'init' in config else None
    encoder = arch(vocab_sz, **config)
    enc = encoder.encoder if tie_weights else None
    decoder = LinearDecoder(vocab_sz, config[meta['hid_name']], output_p, tie_encoder=enc, bias=out_bias)
    model = SequentialRNN(encoder, decoder)
    return model if init is None else model.apply(init)

# Cell
def _pad_tensor(t, bs):
    if t.size(0) < bs: return torch.cat([t, t.new_zeros(bs-t.size(0), *t.shape[1:])])
    return t

# Cell
class SentenceEncoder(Module):
    "Create an encoder over `module` that can process a full sentence."
    def __init__(self, bptt, module, pad_idx=1, max_len=None): store_attr(self, 'bptt,module,pad_idx,max_len')
    def reset(self): getattr(self.module, 'reset', noop)()

    def forward(self, input):
        bs,sl = input.size()
        self.reset()
        mask = input == self.pad_idx
        outs,masks = [],[]
        for i in range(0, sl, self.bptt):
            #Note: this expects that sequence really begins on a round multiple of bptt
            real_bs = (input[:,i] != self.pad_idx).long().sum()
            o = self.module(input[:real_bs,i: min(i+self.bptt, sl)])
            if self.max_len is None or sl-i <= self.max_len:
                outs.append(o)
                masks.append(mask[:,i: min(i+self.bptt, sl)])
        outs = torch.cat([_pad_tensor(o, bs) for o in outs], dim=1)
        mask = torch.cat(masks, dim=1)
        return outs,mask

# Cell
def masked_concat_pool(output, mask, bptt):
    "Pool `MultiBatchEncoder` outputs into one vector [last_hidden, max_pool, avg_pool]"
    lens = output.shape[1] - mask.long().sum(dim=1)
    last_lens = mask[:,-bptt:].long().sum(dim=1)
    avg_pool = output.masked_fill(mask[:, :, None], 0).sum(dim=1)
    avg_pool.div_(lens.type(avg_pool.dtype)[:,None])
    max_pool = output.masked_fill(mask[:,:,None], -float('inf')).max(dim=1)[0]
    x = torch.cat([output[torch.arange(0, output.size(0)),-last_lens-1], max_pool, avg_pool], 1) #Concat pooling.
    return x

# Cell
class PoolingLinearClassifier(Module):
    "Create a linear classifier with pooling"
    def __init__(self, dims, ps, bptt):
        if len(ps) != len(dims)-1: raise ValueError("Number of layers and dropout values do not match.")
        acts = [nn.ReLU(inplace=True)] * (len(dims) - 2) + [None]
        layers = [LinBnDrop(i, o, p=p, act=a) for i,o,p,a in zip(dims[:-1], dims[1:], ps, acts)]
        self.layers = nn.Sequential(*layers)
        self.bptt = bptt

    def forward(self, input):
        out,mask = input
        x = masked_concat_pool(out, mask, self.bptt)
        x = self.layers(x)
        return x, out, out

# Cell
def get_text_classifier(arch, vocab_sz, n_class, seq_len=72, config=None, drop_mult=1., lin_ftrs=None,
                        ps=None, pad_idx=1, max_len=72*20):
    "Create a text classifier from `arch` and its `config`, maybe `pretrained`"
    meta = _model_meta[arch]
    config = ifnone(config, meta['config_clas']).copy()
    for k in config.keys():
        if k.endswith('_p'): config[k] *= drop_mult
    if lin_ftrs is None: lin_ftrs = [50]
    if ps is None:  ps = [0.1]*len(lin_ftrs)
    layers = [config[meta['hid_name']] * 3] + lin_ftrs + [n_class]
    ps = [config.pop('output_p')] + ps
    init = config.pop('init') if 'init' in config else None
    encoder = SentenceEncoder(seq_len, arch(vocab_sz, **config), pad_idx=pad_idx, max_len=max_len)
    model = SequentialRNN(encoder, PoolingLinearClassifier(layers, ps, bptt=seq_len))
    return model if init is None else model.apply(init)