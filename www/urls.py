#!/usr/bin/env python
# -*- coding:utf-8 -*-

import os,re,time,base64,hashlib,logging
from transwarp.web import get,view,post,ctx,interceptor,HttpError
from apis import api,APIValueError,APIError,APIPermissionError,APIResourceNotFoundError,Page
from models import User,Blog,Comment
from config import configs
from markdown import markdown

_COOKIE_NAME = 'awesession'
_COOKIE_KEY = configs.session.secret


def _get_page_index():
    page_index = 1
    try:
        page_index = int(ctx.request.get('page','1'))
    except ValueError:
        pass
    return page_index

def _get_blogs_by_page():
    total = Blog.count_all()
    page = Page(total[0].values()[0],_get_page_index())
    blogs = Blog.find_by('order by created_at desc limit ?,?',page.offset,page.limit)
    return blogs,page

def make_signed_cookie(id,password,max_age):
    #返回加密的cookie
    expires = str(int(time.time() + (max_age or 86400)))
    L = [id,expires,hashlib.md5('%s-%s-%s-%s'%(id,password,expires,_COOKIE_KEY)).hexdigest()]
    return '-'.join(L)

def parse_signed_cookie(cookie_str):
    try:
        L = cookie_str.split('-')
        if len(L) != 3:
            return None
        id,expires,md5 = L
        if int(expires) < time.time():
            return None
        user = User.get(id)
        if user is None:
            return None
        if md5 != hashlib.md5('%s-%s-%s-%s'%(id,user.password,expires,_COOKIE_KEY)).hexdigest():
            return None
        return user
    except:
        return None

# def check_admin():
#     user = ctx.request.user
#     if user and user.admin:
#         return
#     raise APIPermissionError('No permission.')

# @interceptor('/')
# def user_interceptor(next):
#     logging.info('try to bind user from session cookie...')
#     user = None
#     cookie = ctx.request.cookies.get(_COOKIE_NAME)
#     if cookie:
#         logging.info('parse session cookie...')
#         user = parse_signed_cookie(cookie)
#         if user:
#             logging.info('bind user <%s> to session...' % user.email)
#     ctx.request.user = user
#     return next()
#
# @interceptor('/manage/')
# def manage_interceptor(next):
#     user = ctx.request.user
#     if user and user.admin:
#         return next()
#     raise HttpError.seeother('/signin')

def check_login(func):
    def wrapper(*args,**kwargs):
        user = None
        cookie = ctx.request.cookies.get(_COOKIE_NAME)
        if cookie:
            logging.info('parse session cookie...')
            user = parse_signed_cookie(cookie)
            if user:
                logging.info('bind user <%s> to session...' % user.email)
        ctx.request.user = user
        return func(*args,**kwargs)
    return wrapper

def check_admin(func):
    def wrapper(*args,**kwargs):
        user = None
        cookie = ctx.request.cookies.get(_COOKIE_NAME)
        if cookie:
            user = parse_signed_cookie(cookie)
            if user and user.admin:
                logging.info('bind user <%s> to session...' % user.email)
            ctx.request.user = user
            return func(*args,**kwargs)
        else:
            raise HttpError.seeother('/signin')
    return wrapper


_RE_EMAIL = re.compile(r'^[a-z0-9\.\-\_]+\@[a-z0-9\-\_]+(\.[a-z0-9\-\_]+){1,4}$')
_RE_MD5 = re.compile(r'^[0-9a-f]{32}$')

@api
@post('/api/users')
def register_user():
    i = ctx.request.input(name='',email='',password='')
    name = i.name.strip()
    email = i.email.strip().lower()
    password = i.password
    if not name:
        raise APIValueError('name')
    if not email or not _RE_EMAIL.match(email):
        raise APIValueError('email')
    if not password or not _RE_MD5.match(password):
        raise APIValueError('password')
    user = User.find_first('where email=?',email)
    if user:
        raise APIError('register:failed','email','Email is already in use.')
    user = User(name=name,email=email,password=password,image='http://www.gravatar.com/avatar/%s?d=mm&s=120'%hashlib.md5(email).hexdigest())
    user.insert()
    #make session cookie
    cookie = make_signed_cookie(user.id,user.password,None)
    ctx.response.set_cookie(_COOKIE_NAME,cookie)
    return user

@api
@post('/api/authenticate')
def authenticate():
    i = ctx.request.input(remeber='')
    email = i.email.strip().lower()
    password = i.password
    remeber = i.remeber
    user = User.find_first('where email=?',email)
    if user is None:
        raise APIError('auth:failed','email','Invalid email.')
    elif user.password != password:
        raise APIError('auth:failed','password','Invalid password.')
    #make session cookie
    max_age = 604800 if remeber=='true' else None
    cookie = make_signed_cookie(user.id,user.password,max_age)
    ctx.response.set_cookie(_COOKIE_NAME,cookie,max_age=max_age)
    user.password = '******'
    return user

@api
@post('/api/blogs')
@check_login
def api_create_blog():
    i = ctx.request.input(name='',summary='',content='')
    name = i.name.strip()
    summary = i.summary.strip()
    content = i.content.strip()
    if not name:
        raise APIValueError('name','name cannot be empty.')
    if not summary:
        raise APIValueError('summary','summary cannot be empty.')
    if not content:
        raise APIValueError('content','content cannot be empty.')
    user = ctx.request.user
    blog = Blog(user_id=user.id,user_name=user.name,name=name,summary=summary,content=content)
    blog.insert()
    return blog

@api
@get('/api/blogs')
def api_get_blogs():
    format = ctx.request.get('format','')
    blogs,page = _get_blogs_by_page()
    if format == 'html':
        for blog in blogs:
            blog.content = markdown(blog.content)
    return dict(blogs=blogs,page=page)


@api
@get('/api/blogs/:blog_id')
def api_get_blog(blog_id):
    blog = Blog.get(blog_id)
    if blog:
        return blog
    raise APIResourceNotFoundError('Blog')

@api
@post('/api/blogs/:blog_id')
@check_admin
def api_update_blog(blog_id):
    i = ctx.request.input(name='', summary='', content='')
    name = i.name.strip()
    summary = i.summary.strip()
    content = i.content.strip()
    if not name:
        raise APIValueError('name', 'name cannot be empty.')
    if not summary:
        raise APIValueError('summary', 'summary cannot be empty.')
    if not content:
        raise APIValueError('content', 'content cannot be empty.')
    blog = Blog.get(blog_id)
    if blog is None:
        raise APIResourceNotFoundError('Blog')
    blog.name = name
    blog.summary = summary
    blog.content = content
    blog.update()
    return blog

@api
@post('/api/blogs/:blog_id/delete')
@check_admin
def api_delete_blog(blog_id):
    blog = Blog.get(blog_id)
    if blog is None:
        raise APIResourceNotFoundError('Blog')
    blog.delete()
    return dict(id=blog_id)

@api
@post('/api/blogs/:blog_id/comments')
@check_login
def api_create_blog_comment(blog_id):
    user = ctx.request.user
    if user is None:
        raise APIPermissionError('Need signin.')
    blog = Blog.get(blog_id)
    if blog is None:
        raise APIResourceNotFoundError('Blog')
    content = ctx.request.input(content='').content.strip()
    if not content:
        raise APIValueError('content')
    c = Comment(blog_id=blog_id, user_id=user.id, user_name=user.name, user_image=user.image, content=content)
    c.insert()
    return dict(comment=c)

@api
@post('/api/comments/:comment_id/delete')
@check_admin
def api_delete_comment(comment_id):
    comment = Comment.get(comment_id)
    if comment is None:
        raise APIResourceNotFoundError('Comment')
    comment.delete()
    return dict(id=comment_id)

@api
@get('/api/comments')
def api_get_comments():
    total = Comment.count_all()
    page = Page(total[0].values()[0], _get_page_index())
    comments = Comment.find_by('order by created_at desc limit ?,?', page.offset, page.limit)
    return dict(comments=comments, page=page)



@view('blogs.html')
@get('/')
@check_login
def index():
    blogs = Blog.find_all()
    for p in blogs:
        p.summary = markdown(p.summary)
    return dict(blogs=blogs,user=ctx.request.user)

@view('blog.html')
@get('/blog/:blog_id')
@check_login
def blog(blog_id):
    blog = Blog.get(blog_id)
    if blog is None:
        raise HttpError.notfound()
    blog.html_content = markdown(blog.content)
    comments = Comment.find_by('where blog_id=? order by created_at desc limit 1000', blog_id)
    return dict(blog=blog,comments=comments,user=ctx.request.user)


@view('register.html')
@get('/register')
def register():
    return dict()

@view('signin.html')
@get('/signin')
def signin():
    return dict()

@get('/signout')
def signout():
    ctx.response.delete_cookie(_COOKIE_NAME)
    raise HttpError.seeother('/')

@get('/manage/')
def manage_index():
    raise HttpError.seeother('/manage/comments')

@view('manage_blog_edit.html')
@get('/manage/blogs/create')
@check_admin
def manage_blogs_create():
    return dict(id=None,action='/api/blogs',redirect='/manage/blogs',user=ctx.request.user)

@view('manage_blog_edit.html')
@get('/manage/blogs/edit/:blog_id')
@check_admin
def manage_blogs_edit(blog_id):
    blog = Blog.get(blog_id)
    if blog is None:
        raise HttpError.notfound()
    return dict(id=blog.id, name=blog.name, summary=blog.summary, content=blog.content, action='/api/blogs/%s' % blog_id, redirect='/manage/blogs', user=ctx.request.user)

@view('manage_comment_list.html')
@get('/manage/comments')
@check_admin
def manage_comments():
    return dict(page_index=_get_page_index(), user=ctx.request.user)

@view('manage_blogs.html')
@get('/manage/blogs')
@check_admin
def manage_blogs():
    return dict(page_index=_get_page_index(),user=ctx.request.user)

@view('manage_user_list.html')
@get('/manage/users')
@check_admin
def manage_users():
    return dict(page_index=_get_page_index(), user=ctx.request.user)

@api
@get('/api/users')
def api_get_users():
    users = User.find_by('order by created_at desc')
    #把用户口令隐藏
    for u in users:
        u.password = '******'
    return dict(users=users)