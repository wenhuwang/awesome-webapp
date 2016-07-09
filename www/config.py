#!/usr/bin/env python
# -*- coding:utf-8 -*-

"""
配置文件
"""

from transwarp.db import Dict
import config_default

def merge(default,override):
    """
    合并override和default配置文件，返回字典
    """
    r = {}
    for k,v in default.iteritems():
        if k in override:
            if isinstance(v,dict):
                r[k] = merge(v,override[k])
            else:
                r[k] = override[k]
        else:
            r[k] = v
    return r

def toDict(d):
    """
    将一个字典对象转换成一个Dict对象
    """
    D = Dict()
    for k,v in d.iteritems():
        D[k] = toDict(v) if isinstance(v,dict) else v
    return D


configs = config_default.configs

try:
    import config_override
    configs = merge(configs,config_override.configs)
except ImportError:
    pass


configs = toDict(configs)
