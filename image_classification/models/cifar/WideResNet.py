'''
<Reference>
WideResNet for Cifar-100 is from:
[1] Clova AI Research, GitHub repository, https://github.com/clovaai/overhaul-distillation
'''

import math
import torch
import torch.nn as nn
import torch.nn.functional as F

class BasicBlock(nn.Module):
    def __init__(self, in_planes, out_planes, stride, bn_aff = True, shortcut = True, dropRate=0.0):
        super(BasicBlock, self).__init__()
        
        self.shortcut = shortcut
        self.bn_aff = bn_aff
        
        self.bn1 = nn.BatchNorm2d(in_planes, affine = self.bn_aff)
        self.relu1 = nn.ReLU(inplace=True)
        self.conv1 = nn.Conv2d(in_planes, out_planes, kernel_size=3, stride=stride,
                               padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(out_planes, affine = self.bn_aff)
        self.relu2 = nn.ReLU(inplace=True)
        self.conv2 = nn.Conv2d(out_planes, out_planes, kernel_size=3, stride=1,
                               padding=1, bias=False)
        self.droprate = dropRate
        self.equalInOut = (in_planes == out_planes)
        self.convShortcut = (not self.equalInOut) and nn.Conv2d(in_planes, out_planes, kernel_size=1, stride=stride,
                               padding=0, bias=False) or None

    def forward(self, x):
        if not self.equalInOut:
            x = self.relu1(self.bn1(x))
        else:
            out = self.relu1(self.bn1(x))
        out = self.relu2(self.bn2(self.conv1(out if self.equalInOut else x)))
        if self.droprate > 0:
            out = F.dropout(out, p=self.droprate, training=self.training)
        out = self.conv2(out)
        
        if self.shortcut:
            out = torch.add(x if self.equalInOut else self.convShortcut(x), out)
        else:
            out
        return out

class NetworkBlock(nn.Module):
    def __init__(self, nb_layers, in_planes, out_planes, block, stride, bn_aff = True, shortcut = True, dropRate=0.0):
        super(NetworkBlock, self).__init__()
        self.shortcut = shortcut
        self.bn_aff = bn_aff
        self.layer = self._make_layer(block, in_planes, out_planes, nb_layers, stride, dropRate)

    def _make_layer(self, block, in_planes, out_planes, nb_layers, stride, dropRate):
        layers = []
        for i in range(int(nb_layers)):
            layers.append(block(i == 0 and in_planes or out_planes, out_planes, i == 0 and stride or 1, self.bn_aff, self.shortcut, dropRate))
        return nn.Sequential(*layers)

    def forward(self, x):
        return self.layer(x)

class WideResNet(nn.Module):
    def __init__(self, depth, num_classes, widen_factor=1, bn_aff = True, shortcut = True, dropRate=0.0):
        super(WideResNet, self).__init__()
        nChannels = [16, 16*widen_factor, 32*widen_factor, 64*widen_factor]
        assert((depth - 4) % 6 == 0)
        n = (depth - 4) / 6
        block = BasicBlock
        self.bn_aff = bn_aff
        self.shortcut = shortcut
        # 1st conv before any network block
        self.conv1 = nn.Conv2d(3, nChannels[0], kernel_size=3, stride=1, padding=1, bias=False)
        # 1st block
        self.block1 = NetworkBlock(n, nChannels[0], nChannels[1], block, 1, self.bn_aff, self.shortcut, dropRate)
        # 2nd block
        self.block2 = NetworkBlock(n, nChannels[1], nChannels[2], block, 2, self.bn_aff, self.shortcut, dropRate)
        # 3rd block
        self.block3 = NetworkBlock(n, nChannels[2], nChannels[3], block, 2, self.bn_aff, self.shortcut, dropRate)
        # global average pooling and classifier
        self.bn1 = nn.BatchNorm2d(nChannels[3], affine = self.bn_aff)
        self.relu = nn.ReLU(inplace=True)
        self.linear = nn.Linear(nChannels[3], num_classes)
        self.nChannels = nChannels

        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
            elif isinstance(m, nn.BatchNorm2d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()
            elif isinstance(m, nn.Linear):
                m.bias.data.zero_()

    def forward(self, x):
        out = self.conv1(x)
        out = self.block1(out)
        out = self.block2(out)
        out = self.block3(out)
        out = self.relu(self.bn1(out))
        out = F.avg_pool2d(out, 8)
        out = out.view(-1, self.nChannels[3])
        return self.linear(out)

    def get_bn_before_relu(self):
        bn1 = self.block2.layer[0].bn1
        bn2 = self.block3.layer[0].bn1
        bn3 = self.bn1

        return [bn1, bn2, bn3]

    def get_channel_num(self):

        return self.nChannels[1:]

    def extract_feature(self, x, preReLU=False):
        out = self.conv1(x)
        feat1 = self.block1(out)
        feat2 = self.block2(feat1)
        feat3 = self.block3(feat2)
        out = self.relu(self.bn1(feat3))
        out = F.avg_pool2d(out, 8)
        out = out.view(-1, self.nChannels[3])
        out = self.linear(out)

        if preReLU:
            feat1 = self.block2.layer[0].bn1(feat1)
            feat2 = self.block3.layer[0].bn1(feat2)
            feat3 = self.bn1(feat3)

        return [feat1, feat2, feat3], out