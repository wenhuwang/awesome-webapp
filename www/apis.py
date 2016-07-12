#!/usr/bin/env python
# -*- coding:utf-8 -*-

"""
实现以Json数据格式进行交换的RESTful API
设计原因：
    由于API就是把Web App的功能全部封装了，所有通过API操作数据可以极大地把前端和后端
    代码隔离，使得后端代码易于测试，前端代码编写更简单
实现方式：
    一个API也是一个URL的处理函数，我们希望能直接通过一个@api来把函数变成JSON格式的
    REST API，因此我们希望实现一个装饰器，由该装饰器将函数返回值处理成JSON格式。
"""

import json
import logging
import functools
from transwarp.web import ctx

class Page(object):
    #分页功能
    def __init__(self,item_count,page_index=1,page_size=10):
        #初始化分页器的属性
        self.item_count = item_count
        self.page_size = page_size
        self.page_count = item_count // page_size + (1 if item_count % page_size > 0 else 0)
        if (item_count == 0) or (page_index < 1) or (page_index > self.page_count):
            self.offset = 0
            self.limit = 0
            self.page_index = 1
        else:
            self.page_index = page_index
            self.offset = self.page_size * (page_index - 1)
            self.limit = self.page_size
        self.has_next = self.page_index < self.page_count
        self.has_previous = self.page_index > 1

    def __str__(self):
        return 'item_count: %s, page_count: %s, page_index: %s, page_size: %s, offset: %s, limit: %s' % (self.item_count, self.page_count, self.page_index, self.page_size, self.offset, self.limit)

    __repr__ = __str__

def _dump(obj):
    if isinstance(obj, Page):
        return {
            'page_index': obj.page_index,
            'page_count': obj.page_count,
            'item_count': obj.item_count,
            'has_next': obj.has_next,
            'has_previous': obj.has_previous
        }
    raise TypeError('%s is not JSON serializable' % obj)

def dumps(obj):
    """
    序列化对象
    """
    return json.dumps(obj,default=_dump)

class APIError(StandardError):
    """
    存储所有API异常对象的数据
    """
    def __init__(self,error,data="",message=""):
        super(APIError, self).__init__(message)
        self.error = error
        self.data = data
        self.message = message
class APIValueError(APIError):
    """输入不合法异常对象"""
    def __init__(self,field,message=''):
        super(APIValueError, self).__init__('value:invalid',field,message)

class APIResourceNotFoundError(APIError):
    #资源未找到 异常对象
    def __init__(self,field,message=''):
        super(APIResourceNotFoundError, self).__init__('value:notfound',field,message)

class APIPermissionError(APIError):
    #权限 异常对象
    def __init__(self,message=''):
        super(APIPermissionError, self).__init__('permission:forbidden','permission',message)

def api(func):
    """
    将函数返回结果转换成json的装饰器
    @api需要对Error进行处理，我们定义一个APIError是指API调用时发生逻辑错误(比如用户不存在)
    其他的Error视为Bug，返回的错误代码为internalerror

    @app.route('api/test')
    @api
    def api_test():
        return dict(result='123',item=[])
    """
    @functools.wraps(func)
    def _wrapper(*args,**kw):
        try:
            r = dumps(func(*args,**kw))
        except APIError,e:
            r = dumps(dict(error=e.error,data=e.data,message=e.message))
        except Exception,e:
            logging.exception(e)
            r = dumps(dict(error='internalerror',data=e.__class__.__name__,message=e.message))
        ctx.response.content_type = 'application/json'
        return r
    return _wrapper

if __name__ == '__main__':
    import doctest
    doctest.testmod()