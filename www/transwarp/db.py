#!/usr/bin/env python
# -*- coding:utf-8 -*-

"""
设计db模块的原因：
  1. 更简单的操作数据库
      一次数据访问：   数据库连接 => 游标对象 => 执行SQL => 处理异常 => 清理资源。
      db模块对这些过程进行封装，使得用户仅需关注SQL执行。
  2. 数据安全
      用户请求以多线程处理时，为了避免多线程下的数据共享引起的数据混乱，
      需要将数据连接以ThreadLocal对象传入。
设计db接口：
  1.设计原则：
      根据上层调用者设计简单易用的API接口
  2. 调用接口
      1. 初始化数据库连接信息
          create_engine封装了如下功能:
              1. 为数据库连接 准备需要的配置信息
              2. 创建数据库连接(由生成的全局对象engine的 connect方法提供)
          from transwarp import db
          db.create_engine(user='root',
                           password='password',
                           database='test',
                           host='127.0.0.1',
                           port=3306)
      2. 执行SQL DML
          select 函数封装了如下功能:
              1.支持一个数据库连接里执行多个SQL语句
              2.支持链接的自动获取和释放
          使用样例:
              users = db.select('select * from user')
              # users =>
              # [
              #     { "id": 1, "name": "Michael"},
              #     { "id": 2, "name": "Bob"},
              #     { "id": 3, "name": "Adam"}
              # ]
      3. 支持事物
         transaction 函数封装了如下功能:
             1. 事务也可以嵌套，内层事务会自动合并到外层事务中，这种事务模型足够满足99%的需求
"""

import threading
import logging
import functools
import uuid
import time


#创建全局引擎对象
engine = None

def next_id(t=None):
    """
    生成一个唯一id   由 当前时间 + 随机数（由伪随机数得来）拼接得到
    """
    if t is None:
        t = time.time()
    return '%015d%s000' % (int(t*1000),uuid.uuid4().hex)

def _profiling(start,sql=''):
    """
    用于剖析sql的执行时间
    """
    t = time.time() - start
    if t > 0.1:
        logging.warning('[PROFILING] [DB] %s: %s'%(t,sql))
    else:
        logging.info('[PROFILING] [DB] %s: %s'%(t,sql))

def create_engine(user,password,database,host='127.0.0.1',port=3306,**kw):

    import mysql.connector
    global engine
    if engine is not None:
        raise DBError('Engine is already initialized.')
    params =  dict(user=user,password=password,database=database,host=host,port=port)
    defaults = dict(use_unicode=True,charset='utf8',collation='utf8_general_ci',autocommit=False)
    for k,v in defaults.iteritems():
        params[k] = kw.pop(k,v)
    params.update(kw)
    params['buffered'] = True
    engine = _Engine(lambda :mysql.connector.connect(**params))
    logging.info('Init mysql engine <%s> ok.' % hex(id(engine)))


def connection():
    """
    db模块核心函数，用于获取一个数据库连接
    通过_ConnectionCtx对 _db_ctx封装，使得惰性连接可以自动获取和释放，
    也就是可以使用 with语法来处理数据库连接
    _ConnectionCtx    实现with语法
    ^
    |
    _db_ctx           _DbCtx实例
    ^
    |
    _DbCtx            获取和释放惰性连接
    ^
    |
    _LasyConnection   实现惰性连接
    """
    return _ConnectionCtx()

def with_connection(func):
    """
    设计一个装饰器 替换with语法，让代码更优雅
    比如:
    @with_connection
    def foo(*args, **kw):
        f1()
        f2()
        f3()
    """
    @functools.wraps(func)
    def _wrapper(*args,**kw):
        with _ConnectionCtx():
            return func(*args,**kw)
    return _wrapper

def transaction():
    """
    db模块核心函数 用于实现事物功能
    支持事物:
        with db.transaction():
            db.select('...')
            db.update('...')
            db.update('...')
    支持事物嵌套:
        with db.transaction():
            transaction1
            transaction2
            ...
    """
    return _TransactionCtx()

def with_transaction(func):
    """
    设计一个装饰器 替换with语法，让代码更优雅
    比如:
        @with_transaction
        def do_in_transaction():
    """
    @functools.wraps(func)
    def _wrapper(*args,**kw):
        start = time.time()
        with _TransactionCtx():
            func(*args,**kw)
        _profiling(start)
    return _wrapper

@with_connection
def _select(sql,first,*args):
    """
    执行SQL，返回一个结果 或者多个结果组成的列表
    """
    global _db_ctx
    cursor = None
    sql = sql.replace('?','%s')
    logging.info('SQL:%s,ARGS:%s'%(sql,args))
    try:
        cursor = _db_ctx.connection.cursor()
        cursor.execute(sql,args)
        if cursor.description:
            names = [x[0] for x in cursor.description]
        if first:
            values = cursor.fetchone()
            if not values:
                return None
            return Dict(names,values)
        return [Dict(names,x) for x in cursor.fetchall()]
    finally:
        if cursor:
            cursor.close()

def select_one(sql,*args):
    """
    执行SQL 仅返回一个结果
    如果没有结果 返回None
    如果有1个结果，返回一个结果
    如果有多个结果，返回第一个结果
    """
    return _select(sql,True,*args)

def select_int(sql,*args):
    """
    执行一个sql 返回一个数值，
    注意仅一个数值，如果返回多个数值将触发异常
    """
    d = _select(sql,True,*args)
    if len(d) != 1:
        raise MultiColumnsError('Except only one column.')
    return d.values()[0]

def select(sql,*args):
    """执行sql 以列表形式返回结果"""
    return _select(sql,False,*args)

@with_connection
def _update(sql,*args):
    # 执行update 语句，返回update的行数
    global _db_ctx
    cursor = None
    sql = sql.replace('?','%s')
    logging.info('SQL:%s,ARGS:%s'%(sql,args))
    try:
        cursor = _db_ctx.connection.cursor()
        cursor.execute(sql,args)
        r = cursor.rowcount
        if _db_ctx.transactions == 0:
            logging.info('auto commit')
            _db_ctx.connection.commit()
        return r
    finally:
        if cursor:
            cursor.close()

def update(sql,*args):
    # 执行update语句，返回update的行数
    return _update(sql,*args)

def insert(table,**kw):
    cols,args = zip(*kw.iteritems())
    sql = 'insert into `%s`(%s) values(%s)'%(table,','.join(['`%s`'% col for col in cols]),','.join(['?' for i in range(len(cols))]))
    return _update(sql,*args)



class Dict(dict):
    def __init__(self,names=(),values=(),**kw):
        super(Dict,self).__init__(**kw)
        for k,v in zip(names,values):
            self[k] = v

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Dict' object has no attribute '%s'" % key)

    def __setattr__(self, key, value):
        self[key] = value


class DBError(Exception):
    pass

class MultiColumnsError(DBError):
    pass

#数据库引擎对象
class _Engine(object):
    def __init__(self,connect):
        self._connect = connect
    def connect(self):
        return self._connect()

class _LasyConnection(object):
    """
    惰性连接对象
    仅当需要cursor对象时，才连接数据库，获取连接
    """
    def __init__(self):
        self.connection = None

    def cursor(self):
        if self.connection is None:
            _connection = engine.connect()
            logging.info('[CONNECTION] [OPEN] connection <%s>...'%hex(id(_connection)))
            self.connection = _connection
        return self.connection.cursor()

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def cleanup(self):
        if self.connection:
            _connection = self.connection
            self.connection = None
            logging.info('[CONNECTION] [CLOSE] connection <%s>...'%hex(id(_connection)))
            _connection.close()

#持有数据库连接的上下文对象
class _DbCtx(threading.local):
    """
    db模块的核心对象, 数据库连接的上下文对象，负责从数据库获取和释放连接
    取得的连接是惰性连接对象，因此只有调用cursor对象时，才会真正获取数据库连接
    该对象是一个 Thread local对象，因此绑定在此对象上的数据 仅对本线程可见
    """
    def __init__(self):
        self.connection = None
        self.transactions = 0 #事务

    def is_init(self):
        """
        :return:返回一个布尔值，用于判断此对象的初始状态
        """
        return not self.connection is None

    def init(self):
        """
         初始化连接的上下文对象，获得一个惰性连接对象
        """
        logging.info('open lazy connection...')
        self.connection = _LasyConnection()
        self.transactions = 0

    def cleanup(self):
        """
         清理连接对象，关闭连接
        """
        self.connection.cleanup()
        self.connection = None

    def cursor(self):
        """
        获取cursor对象，真正获取数据库连接
        """
        return self.connection.cursor()

# thread-local db context:
_db_ctx = _DbCtx()

class _ConnectionCtx(object):
    """
    因为_DbCtx实现了连接的 获取和释放，但是并没有实现连接
    的自动获取和释放，_ConnectCtx在 _DbCtx基础上实现了该功能，
    因此可以对 _ConnectCtx 使用with 语法，比如：
    with connection():
        pass
        with connection():
            pass
    """
    def __enter__(self):
        """
        获取一个惰性连接对象
        """
        global _db_ctx
        self.should_cheanup = False
        if not _db_ctx.is_init():
            _db_ctx.init()
            self.should_cheanup = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        释放连接
        """
        global _db_ctx
        if self.should_cheanup:
            _db_ctx.cleanup()

class _TransactionCtx(object):

    def __enter__(self):
        global _db_ctx
        self.should_close_conn = False
        if not _db_ctx.is_init():
            _db_ctx.init()
            self.should_close_conn = True
        _db_ctx.transactions += 1
        logging.info('begin transaction...' if _db_ctx.transactions == 1 else 'join current transaction...')
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        global _db_ctx
        _db_ctx.transactions -= 1
        try:
            if _db_ctx.transactions == 0:
                if exc_type is None:
                    self.commit()
                else:
                    self.rollback()
        finally:
            if self.should_close_conn:
                _db_ctx.cleanup()

    def commit(self):
        global _db_ctx
        logging.info('commit transaction...')
        try:
            _db_ctx.connection.commit()
            logging.info('commit ok.')
        except:
            logging.warning('commmit failed.try rollback...')
            _db_ctx.connection.rollback()
            logging.warning('rollback ok.')

    def rollback(self):
        global _db_ctx
        logging.warning('rollback transaction...')
        _db_ctx.connection.rollback()
        logging.info('rollback ok.')


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    create_engine('root','qwerty','awesome-webapp')
    #update('create table user (id int PRIMARY key,name VARCHAR(20),email VARCHAR(30),password VARCHAR(20))')
    u1 = dict(id=3,name='wenhu3',email='3@qq.com',password='123')
    #update('update user SET name=?','wenhu1')
    #update('INSERT user(id,name,email,password) VALUES(?,?,?,?)',2,'wenhu2','1@qq.com','123')
    insert('user',**u1)
    u1 = select('select * from user where id=?',3)
    print u1
    import doctest
    doctest.testmod()