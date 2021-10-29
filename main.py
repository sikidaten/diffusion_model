import os
import pickle as pkl
import shutil

import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision
import torchvision.transforms as T

import utils.fid as lfid
import utils.util as U
from model.diffusion import Diffusion
from model.res_unet import Res_UNet
from plotter import Plotter
from utils.gtmodel import fid_inception_v3
from utils.tfrecord import TFRDataloader


def train():
    for idx,data in enumerate(loader):
        global gidx
        gidx+=1
        stat = diffusion.trainbatch(data, gidx)
        print(f'{epoch}/{cfg["epoch"]} {gidx % len(loader)}/{len(loader)} {stat["loss"]:.2}')
        if idx % 2000 == 0:
            for stride in cfg['stride']:
                U.save_image(diffusion.sample(stride=stride, embch=cfg['model']['embch'], x=xT,img=data),
                             f'{savefolder}/{gidx}_{stride}.jpg', s=0.5, m=0.5)
            if (cfg['fid']):
                fid = check_fid(2000)
                pltr.addvalue({'fid': fid}, gidx)
            torch.save(denoizer.module.state_dict(),f'{savefolder}/model.pth')
            with open(f'{savefolder}/epoch.txt','w') as f:
                f.write(f'{epoch}')


@torch.no_grad()
def check_fid(num_image):
    mvci = lfid.MeanCoVariance_iter(device)
    for idx in range(num_image // cfg['batchsize'] + 1):
        print(idx, num_image, cfg['batchsize'])
        x = torch.randn(cfg['samplebatchsize'], cfg['model']['in_ch'], cfg['model']['size'], cfg['model']['size']).to(
            device)
        x = diffusion.sample(stride=cfg['stride'], embch=cfg['model']['embch'], x=x)
        x = F.interpolate(x, (299, 299))
        mvci.iter(inception(x))
    fid = lfid.fid(realsigma, realmu, *mvci.get(isbias=True))
    print(f'fid:{fid}')
    return fid


if __name__ == "__main__":
    import argparse
    import yaml

    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='model/config/resunet.yaml')
    parser.add_argument('--device', default='cuda')
    parser.add_argument('--datasetpath', default='../data/')
    parser.add_argument('--savefolder', default='tmp')
    parser.add_argument('--restart', default=False, action='store_true')
    args = parser.parse_args()

    savefolder = f'result/{args.savefolder}'
    device = args.device
    if not args.restart:
        os.makedirs('result', exist_ok=True)
        shutil.rmtree(savefolder, ignore_errors=True)
        os.mkdir(savefolder)
        shutil.copy(args.model, f'{savefolder}/cfg.yaml')
    with open(f'{savefolder}/cfg.yaml') as file:
        cfg = yaml.safe_load(file)
    denoizer = Res_UNet(**cfg['model']).to(device)
    startepoch=0
    if args.restart:
        denoizer.load_state_dict(torch.load(f'{savefolder}/model.pth'))
        with open(f'{savefolder}/epoch.txt') as f:
            startepoch=int(f.read().strip())
    if cfg['loss'] == 'mse':
        criterion = nn.MSELoss()
    if device == 'cuda':
        denoizer = torch.nn.DataParallel(denoizer)
    iscls = False
    numcls = None
    if cfg['dataset'] == 'celeba':
        loader = TFRDataloader(path=args.datasetpath + '/celeba.tfrecord',
                               batch=cfg['batchsize'] // cfg['diffusion']['subdivision'],
                               size=cfg['model']['size'], s=0.5, m=0.5)
        numimg=202589
    elif cfg['dataset'] == 'stl10':
        loader = torch.utils.data.DataLoader(
            torchvision.datasets.STL10('../data/', transform=T.Compose([T.Resize(cfg['model']['size']), T.ToTensor(),T.Normalize([0.5,0.5,0.5],[0.5,0.5,0.5])]),
                                       download=True), num_workers=4, batch_size=cfg['batchsize'])
        iscls = True
        numcls = 10
        numimg=157*32
    if cfg['epoch'] == -1:
        cfg['epoch'] = int(500000 / numimg * cfg['batchsize']) * cfg['diffusion']['subdivision']
    diffusion = Diffusion(denoizer=denoizer, criterion=criterion, device=device, iscls=iscls, numcls=numcls,
                          **cfg['diffusion'])
    xT = torch.randn(cfg['samplebatchsize'], cfg['model']['in_ch'], cfg['model']['size'], cfg['model']['size']).to(
        device)
    inception = fid_inception_v3().to(device)
    with open('celeba_real.pkl', 'rb') as f:
        realsigma, realmu = pkl.load(f)
        realsigma = realsigma.to(device)
        realmu = realmu.to(device)
    pltr = Plotter(f'{savefolder}/graph.jpg')

    gidx=0
    for epoch in range(startepoch,cfg['epoch']):
        train()
