# coding=utf-8
from shopcart.models import System_Config, Email, Serial_Number
# 引入分页组件
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template import Context, loader
from captcha.models import CaptchaStore
from captcha.helpers import captcha_image_url
from django.db import transaction
from django.utils.translation import ugettext as _
import datetime, uuid, os
from django.core.serializers import serialize, deserialize
from django.db.models.query import QuerySet
from django.template.response import TemplateResponse
from django.db import models
import threading
# import the logging library
import logging

# Get an instance of a logger
logger = logging.getLogger('icetus.shopcart')


# 返回文件名和后缀
def split_filename(filename):
	index = filename.rfind('.')
	if index == -1:
		return filename, ''
	else:
		return filename[0:index], filename[index + 1:]


def convert_image_thumb_name(filename, method='i2t'):
	if method == 'i2t':
		name, ext = split_filename(filename)
	logger.debug('ext:%s' % ext)
	if ext:
		return name + '-thumb' + '.' + ext
	else:
		return name


# 去掉网址最后的‘/’
def url_with_out_slash(url):
	if url.endswith('/'):
		url = url[:-1]
	return url


# 强制指定自定义的TDK
def customize_tdk(ctx, tdk):
	if tdk:
		if tdk['page_title']:
			ctx['page_name'] = tdk['page_title']
		if tdk['keywords']:
			ctx['page_key_words'] = tdk['keywords']
		if tdk['short_desc']:
			ctx['page_description'] = tdk['short_desc']
	return ctx


# 获取客户端ip
def get_remote_ip(request):
	if 'HTTP_X_FORWARDED_FOR' in request.META:
		ip = request.META['HTTP_X_FORWARDED_FOR']
		logger.debug('There is HTTP_X_FORWARDED_FOR in request.META,ip is:%s' % ip)
	else:
		ip = request.META['REMOTE_ADDR']
		logger.debug('Get ip from REMOTE_ADDR is:%s' % ip)
	return ip


def add_captcha(ctx):
	hashkey = CaptchaStore.generate_key()
	imgage_url = captcha_image_url(hashkey)
	ctx['hashkey'] = hashkey
	ctx['imgage_url'] = imgage_url
	return ctx


def get_serial_number():
	current_date = datetime.datetime.now().strftime('%Y%m%d')
	# 手动让select for update和update语句发生在一个完整的事务里面
	with transaction.atomic():
		# 使用select_for_update来保证并发请求同时只有一个请求在处理，其他的请求
		# 等待锁释放
		try:
			serial_number = Serial_Number.objects.select_for_update().get(work_date=current_date)
		except:
			serial_number = Serial_Number.objects.create(work_date=current_date)
			serial_number.save()
			return format_serial_number(serial_number)

		serial_number.serial_number = serial_number.serial_number + 1
		serial_number.save()
		return format_serial_number(serial_number)


def format_serial_number(serial_number):
	suffix = ''
	for i in range(len(str(serial_number.serial_number)), 8 + 1):
		suffix = '0' + suffix
	return serial_number.work_date + suffix + str(serial_number.serial_number)


def my_pagination(request, queryset, display_amount=10, after_range_num=5, bevor_range_num=4):
	# 尝试获取每页显示的数量
	try:
		display_amount = int(request.GET.get('page_amount'))
	except:
		pass

	# 按参数分页
	paginator = Paginator(queryset, display_amount)
	try:
		# 得到request中的page参数
		page = int(request.GET.get('page'))
	except:
		# 默认为1
		page = 1
	try:
		# 尝试获得分页列表
		objects = paginator.page(page)
	# 如果页数不存在
	except EmptyPage:
		# 获得最后一页
		objects = paginator.page(paginator.num_pages)
	# 如果不是一个整数
	except:
		# 获得第一页
		objects = paginator.page(1)
	# 根据参数配置导航显示范围
	if page >= after_range_num:
		page_range = paginator.page_range[page - after_range_num:page + bevor_range_num]
	else:
		page_range = paginator.page_range[0:page + bevor_range_num]
	return objects, page_range, page


def get_system_parameters():
	parameter_list = System_Config.objects.all()
	dict = {}
	for parameter in parameter_list:
		dict[parameter.name] = parameter.val

	# 当前时间
	dict['current_date'] = datetime.datetime.now()
	return dict


# 邮件异步发送类
class MailThread(threading.Thread):
	def __init__(self, **kwargs):
		logger.debug('mail thread init ...')
		threading.Thread.__init__(self)
		self.paras = kwargs

	def run(self):
		logger.debug('start send mail thread ...')
		logger.debug('self.paras.smtp_host: %s' % self.paras['smtp_host'])
		logger.debug('self.paras.username: %s' % self.paras['username'])
		logger.debug('self.paras.password: %s' % self.paras['password'])
		my_send_mail(ctx=self.paras['ctx'], send_to=self.paras['send_to'], title=self.paras['title'],
					 template_path=self.paras['template_path'], username=self.paras['username'],
					 password=self.paras['password'], smtp_host=self.paras['smtp_host'], sender=self.paras['sender'],
					 is_ssl=self.paras['is_ssl'])


def my_send_mail(ctx, send_to, title, template_path, username, password, smtp_host, sender, is_ssl=False):
	logger.debug('Enter my_send_mail function.')
	t = loader.get_template(template_path)
	html_content = t.render(Context(ctx))

	logger.debug('0 send_to:%s , username:%s , password: , host:%s ' % (send_to, username, smtp_host))

	if is_ssl:
		logger.debug('Using SSL')
		import smtplib
		from email.mime.text import MIMEText

		msg = MIMEText(html_content, _subtype='html')
		msg['Subject'] = title
		msg['From'] = sender
		msg['To'] = send_to

		s = None
		try:
			logger.debug('1 username:%s , password:%s , host:%s ' % (username, password, smtp_host))
			logger.debug('1')
			s = smtplib.SMTP_SSL(smtp_host, 465)
			logger.debug('2')
			s.login(username, password)
			logger.debug('3')
			s.sendmail(username, send_to, msg.as_string())
			logger.debug('4')
			s.quit()
			logger.debug('5')
		except Exception as err:
			logger.error('Mail send error: %s' % err)
		finally:
			if s:
				try:
					s.quit()
				except:
					pass
	else:
		try:
			logger.debug('Not Using SSL')
			conn = get_connection()	 # 返回当前使用的邮件后端的实例
			logger.debug('1')
			conn.username = username  # 更改用户名
			conn.password = password  # 更改密码
			conn.host = smtp_host  # 设置邮件服务器
			logger.debug('1.5')
			logger.debug('1 username:%s , password:%s , host:%s ' % (conn.username, conn.password, conn.host))
			logger.debug('2')

			try:
				conn.open()	 # 打开连接
				logger.debug('3')
			except Exception as connerr:
				logger.debug('3.5')
				logger.error('Conn.Open Error. Error Message : %s' % connerr)
			finally:
				logger('3.999')

			logger.debug('3.6')

			mail_list = [send_to, ]
			logger.debug('4:%s' % mail_list)
			EMAIL_HOST_USER = sender
			subject, from_email, to = title, EMAIL_HOST_USER, mail_list

			msg = EmailMultiAlternatives(subject, html_content, from_email, to)
			msg.attach_alternative(html_content, "text/html")
			conn.send_messages([msg, ])	 # 我们用send_messages发送邮件
			logger.info('Mail send success! target:%s' % to)
		except Exception as err:
			logger.error('Mail send error：' + str(err))
		finally:
			try:
				if conn:
					logger.info('Close connection：' + str(conn))
					conn.close()  # 发送完毕记得关闭连接
			except:
				pass


def count_file_size(path):
	size = 0
	for root, dirs, files in os.walk(path, True):
		size += sum([os.path.getsize(os.path.join(root, name)) for name in files])
	return size


def handle_uploaded_file(f, type='other', product_sn='-1', file_name_type='random', manual_name='noname',
						 same_name_handle='reject',scale_param=(False,1280,1280)):
	file_name = ""

	file_names = {}

	if not type.endswith('/'):
		type += '/'
	if not product_sn.endswith('/'):
		product_sn += '/'

	destination = None
	try:
		path = 'media/' + type + product_sn + 'images/'
		import os
		if not os.path.exists(path):
			os.makedirs(path)

		ext = f.name.split('.')[-1]
		logger.debug('filename origin:' + str(f.name))
		logger.debug(str(ext))

		# 允许上传的类型
		file_allow = ['JPG', 'JPEG', 'PNG', 'GIF']
		try:
			file_allow_list = System_Config.objects.get(name='file_upload_allow').val
			file_allow = file_allow_list.split(',')
		except Exception as err:
			logger.info('File upload allow did not set. Default is [JPG,JPEG,PNG,GIF]. Error Message:%s' % err)
		
		if ext.upper() not in file_allow:
			file_names['upload_result'] = False
			file_names['upload_error_msg'] = '%s 类型的文件不允许上传。只能上传 %s 类型的文件。' % (ext,file_allow)
			return file_names
			#raise Exception('%s File type is not allowed to upload.' % [ext])

		# 20160616,koala加入对文件名生成的生成规则
		real_name = ''
		real_thumb = ''
		real_path = path
		if file_name_type == 'random':
			random_name = str(uuid.uuid1())
			file_name = path + random_name + '.' + ext
			file_thumb_name = path + random_name + '-thumb' + '.' + ext
			real_name = random_name + '.' + ext
			real_thumb = random_name + '-thumb' + '.' + ext
		elif file_name_type == 'origin':

			file_name = path + f.name
			name_list_tmp = f.name.split('.')
			length = len(name_list_tmp)
			name_list_tmp[length - 2] = name_list_tmp[length - 2] + '-thumb'
			file_thumb_name = path + '.'.join(name_list_tmp)

			real_name = f.name
			real_thumb = '.'.join(name_list_tmp)

		elif file_name_type == 'manual':
			file_name = path + manual_name + '.' + ext
			file_thumb_name = path + manual_name + '-thumb' + '.' + ext

			real_name = manual_name + '.' + ext
			real_thumb = manual_name + '-thumb' + '.' + ext

		else:
			raise Exception('file upload failed')

		logger.info('real_name : %s , real_thumb : %s' % (real_name, real_thumb))

		# 判断文件是否已经存在
		if os.path.exists(file_name):
			if same_name_handle == 'reject':
				file_names['upload_result'] = False
				file_names['upload_error_msg'] = 'File already exists.'
				raise Exception('File already exists.')
			elif same_name_handle == 'rewrite':
				# 覆盖，无需处理
				pass
			else:
				raise Exception('No such method: %s' % same_name_handle)

		destination = open(file_name, 'wb+')
		logger.debug('file_name: %s' % file_name)
		for chunk in f.chunks():
			destination.write(chunk)
		destination.close()
		
		#对太大的文件，进行缩放
		if scale_param[0]:
			scale_result = thumbnail(file_name,'','scale',scale_param[1],scale_param[2])

		result = thumbnail(file_name, file_thumb_name)
		if not result:
			file_names['upload_result'] = False
			file_names['upload_error_msg'] = 'Thumbnail failed.'
			raise Exception('Thumbnail failed.')
		else:
			file_names['upload_result'] = True
			file_names['image'] = file_name
			file_names['thumb'] = file_thumb_name
			file_names['real_name'] = real_name
			file_names['real_thumb'] = real_thumb
			file_names['real_path'] = real_path
			file_names['image_url'] = System_Config.get_base_url() + '/' + file_name
			file_names['thumb_url'] = System_Config.get_base_url() + '/' + file_thumb_name
	except Exception as e:
		# pass
		logger.error(str(e))
	finally:
		if destination:
			destination.close()
	return file_names


def handle_uploaded_attachment_file(f, f2, type='other', product_sn='-1', file_name_type='random', manual_name='noname',
									same_name_handle='reject'):
	file_name = ""

	file_names = {}
	if f2 is None:
		f2 = f

	if not type.endswith('/'):
		type += '/'
	if not product_sn.endswith('/'):
		product_sn += '/'

	destination = None
	try:
		# path = 'media/' + type + product_sn
		path = 'media/' + 'product/' + product_sn + type
		logger.debug('查看product_sn' + product_sn)
		logger.debug('查看路径' + path)

		import os
		if not os.path.exists(path):
			os.makedirs(path)

		ext = f.name.split('.')[-1]
		ext2 = f2.name.split('.')[-1]
		logger.debug('filename origin:' + str(f.name))
		logger.debug('filename origin:' + str(f2.name))
		logger.debug(str(ext))
		logger.debug(str(ext2))
		# 允许上传的类型
		file_allow = ['JPG', 'JPEG', 'PNG', 'GIF', 'PDF', 'ZIP', 'RAR']
		if ext.upper() not in file_allow:
			raise Exception('%s File type is not allowed to upload.' % [ext])
		if ext2.upper() not in file_allow:
			raise Exception('%s File type is not allowed to upload.' % [ext])
		# 20160616,koala加入对文件名生成的生成规则
		real_name = ''
		real_thumb = ''

		real_path = path
		if file_name_type == 'random':
			random_name = str(uuid.uuid1())
			file_name = path + random_name + '.' + ext
			file_thumb_name = path + random_name + '-thumb' + '.' + ext2
			real_name = random_name + '.' + ext
			real_thumb = random_name + '-thumb' + '.' + ext2

		elif file_name_type == 'origin':

			file_name = path + f.name
			name_list_tmp = f.name.split('.')
			length = len(name_list_tmp)
			name_list_tmp[length - 2] = name_list_tmp[length - 2] + '-thumb'
			file_thumb_name = path + f2.name

			real_name = f.name
			real_thumb = f2.name


		elif file_name_type == 'manual':
			file_name = path + manual_name + '.' + ext
			file_thumb_name = path + manual_name + '-thumb' + '.' + ext2
			real_name = manual_name + '.' + ext
			real_thumb = manual_name + '-thumb' + '.' + ext2

		else:
			raise Exception('file upload failed')

		logger.info('real_name : %s' % (real_name))
		logger.info('thumb_name : %s' % (real_thumb))
		# 判断文件是否已经存在
		if os.path.exists(file_name):
			if same_name_handle == 'reject':
				file_names['upload_result'] = False
				file_names['upload_error_msg'] = 'File already exists.'
				raise Exception('File already exists.')
			elif same_name_handle == 'rewrite':
				# 覆盖，无需处理
				pass
			else:
				raise Exception('No such method: %s' % same_name_handle)

		destination = open(file_name, 'wb+')
		logger.debug('file_name: %s' % file_name)
		for chunk in f.chunks():
			destination.write(chunk)
		destination.close()

		destination2 = open(file_thumb_name, 'wb+')
		logger.debug('file_thumb_name: %s' % file_thumb_name)
		for chunk in f2.chunks():
			destination2.write(chunk)
		destination2.close()

		# result = thumbnail(file_name, file_thumb_name)
		# if not result:
		#	  file_names['upload_result'] = False
		# file_names['upload_error_msg'] = 'Thumbnail failed.'
		# raise Exception('Thumbnail failed.')
		# else:

		file_names['upload_result'] = True

		file_names['image'] = file_name

		file_names['thumb'] = file_thumb_name

		file_names['real_name'] = real_name

		file_names['real_thumb'] = real_thumb

		file_names['real_path'] = real_path

		file_names['image_url'] = System_Config.get_base_url() + '/' + file_name

		file_names['thumb_url'] = System_Config.get_base_url() + '/' + file_thumb_name

	except Exception as e:
		# pass
		logger.error(str(e))
	finally:
		if destination:
			destination.close()
	return file_names

# def handle_uploaded_attachment_article_file(f, type='other', product_sn='-1', file_name_type='random', manual_name='noname',
#									  same_name_handle='reject'):
#	  file_name = ""
#
#	  file_names = {}
#	  # if f2 is None:
#	  #		f2 = f
#
#	  if not type.endswith('/'):
#		  type += '/'
#	  if not product_sn.endswith('/'):
#		  product_sn += '/'
#
#	  destination = None
#	  try:
#		  path_images = 'media/' + 'article/' + product_sn + 'images/'
#		  path_attachment = 'media/' + 'article/' + product_sn + 'attachment/'
#
#		  import os
#		  if not os.path.exists(path_images):
#			  os.makedirs(path_images)
#		  if not os.path.exists(path_attachment):
#			  os.makedirs(path_attachment)
#		  ext = f.name.split('.')[-1]
#		  # ext2 = f2.name.split('.')[-1]
#		  logger.debug('filename origin:' + str(f.name))
#		  # logger.debug('filename origin:' + str(f2.name))
#		  logger.debug(str(ext))
#		  # logger.debug(str(ext2))
#		  # 允许上传的类型
#		  file_allow = ['JPG', 'JPEG', 'PNG', 'GIF', 'PDF', 'ZIP', 'RAR']
#		  if ext.upper() not in file_allow:
#			  raise Exception('%s File type is not allowed to upload.' % [ext])
#		  if ext2.upper() not in file_allow:
#			  raise Exception('%s File type is not allowed to upload.' % [ext])
#		  # 20160616,koala加入对文件名生成的生成规则
#		  real_name = ''
#		  real_thumb = ''
#
#		  real_path_images = path_images
#		  real_path_attachment = path_attachment
#		  if file_name_type == 'random':
#			  random_name = str(uuid.uuid1())
#			  file_name = real_path_attachment + random_name + '.' + ext
#			  file_thumb_name = real_path_images + random_name + '-thumb' + '.' + ext2
#			  real_name = random_name + '.' + ext
#			  real_thumb = random_name + '-thumb' + '.' + ext2
#
#		  elif file_name_type == 'origin':
#
#			  file_name = real_path_attachment + f.name
#			  name_list_tmp = f.name.split('.')
#			  length = len(name_list_tmp)
#			  name_list_tmp[length - 2] = name_list_tmp[length - 2] + '-thumb'
#			  file_thumb_name = real_path_images + f2.name
#
#			  real_name = f.name
#			  real_thumb = f2.name
#
#
#		  elif file_name_type == 'manual':
#			  file_name = real_path_attachment + manual_name + '.' + ext
#			  file_thumb_name = real_path_images + manual_name + '-thumb' + '.' + ext2
#			  real_name = manual_name + '.' + ext
#			  real_thumb = manual_name + '-thumb' + '.' + ext2
#
#		  else:
#			  raise Exception('file upload failed')
#
#		  logger.info('real_name : %s' % (real_name))
#		  logger.info('thumb_name : %s' % (real_thumb))
#		  # 判断文件是否已经存在
#		  if os.path.exists(file_name):
#			  if same_name_handle == 'reject':
#				  file_names['upload_result'] = False
#				  file_names['upload_error_msg'] = 'File already exists.'
#				  raise Exception('File already exists.')
#			  elif same_name_handle == 'rewrite':
#				  # 覆盖，无需处理
#				  pass
#			  else:
#				  raise Exception('No such method: %s' % same_name_handle)
#
#		  destination = open(file_name, 'wb+')
#		  logger.debug('file_name: %s' % file_name)
#		  for chunk in f.chunks():
#			  destination.write(chunk)
#		  destination.close()
#
#		  destination2 = open(file_thumb_name, 'wb+')
#		  logger.debug('file_thumb_name: %s' % file_thumb_name)
#		  for chunk in f2.chunks():
#			  destination2.write(chunk)
#		  destination2.close()
#
#		  # result = thumbnail(file_name, file_thumb_name)
#		  # if not result:
#		  #		file_names['upload_result'] = False
#		  # file_names['upload_error_msg'] = 'Thumbnail failed.'
#		  # raise Exception('Thumbnail failed.')
#		  # else:
#
#		  file_names['upload_result'] = True
#
#		  file_names['image'] = file_name
#
#		  file_names['thumb'] = file_thumb_name
#
#		  file_names['real_name'] = real_name
#
#		  file_names['real_thumb'] = real_thumb
#
#		  file_names['real_path'] = real_path_attachment
#
#		  file_names['image_url'] = System_Config.get_base_url() + '/' + file_name
#
#		  file_names['thumb_url'] = System_Config.get_base_url() + '/' + file_thumb_name
#
#	  except Exception as e:
#		  # pass
#		  logger.error(str(e))
#	  finally:
#		  if destination:
#			  destination.close()
#	  return file_names


# 获取一个文件内容
def read_file(targetDir, filename):
	targetFile = os.path.join(targetDir, filename)
	logger.info('Start to read file : %s' % targetFile)
	if os.path.isfile(targetFile):
		fp = open(targetFile)
		try:
			content = fp.read()
		except Exception as err:
			logger.error('Read file %s error. Error Message: %s' % (fp, err))
			content = None
		finally:
			if fp is not None:
				try:
					fp.close()
				except:
					logger.error('Can not close file %s' % fp)
					pass
		return content
	else:
		return None


# 删除文件夹下所有文件
def remove_file_in_dir(targetDir, is_recursive=False):
	for file in os.listdir(targetDir):
		targetFile = os.path.join(targetDir, file)
		if os.path.isfile(targetFile):
			os.remove(targetFile)


# 强制删除整个文件夹
def remove_dir_all(targetDir):
	logger.info('targetDir: %s to be delete....' % targetDir)
	if targetDir:
		import shutil
		try:
			shutil.rmtree(targetDir)
		except Exception as err:
			logger.error('Remove dir faild. Error Message : %s' % err)


def remove_file(targetDir, file, thumb=None):
	targetFile = os.path.join(targetDir, file)
	logger.info('File %s is deleting....' % targetFile)

	result = True
	if os.path.isfile(targetFile):
		try:
			os.remove(targetFile)
		except Exception as err:
			logger.error('File %s delete faild. \n Error Message:%s' % (targetFile, err))
			return False

	if thumb:
		targetFile = os.path.join(targetDir, thumb)
	if os.path.isfile(targetFile):
		try:
			os.remove(targetFile)
		except Exception as err:
			logger.error('File %s delete faild. \n Error Message:%s' % (targetFile, err))
			return False

	return result


def thumbnail(file_name, file_thumb_name , type = 'default' , width = -1 , height = -1):
	# 生成缩略图
	from PIL import Image
	try:
		img = Image.open(file_name)
		
		if type == 'default':
			width = int(System_Config.objects.get(name='thumb_width').val)
			logger.debug('系统参数thumb_width:%s' % [width])
			img.thumbnail((width, width), Image.ANTIALIAS)	# 对图片进行等比缩放
			logger.debug('thumb_file:%s' % file_thumb_name)
			img.save(file_thumb_name)  # 保存图片
		elif type == 'scale':
			logger.debug('scale width:%s , height:%s' % (width,height))
			img.thumbnail((width, height), Image.ANTIALIAS)	# 对图片进行等比缩放
			img.save(file_name)  # 保存图片到原来的图片
			logger.info('Scale success , a image [%s] has been saved.' % file_name)
		return True
	except Exception as err:
		logger.error('thumbnail failed: %s' % err)
		return False
	finally:
		if img:
			img.close()


class Stack():
	def __init__(self, size):
		self.size = size;
		self.stack = [];
		self.top = -1;

	def push(self, ele):  # 入栈之前检查栈是否已满
		if self.isfull():
			raise Exception("out of range");
		else:
			self.stack.append(ele);
			self.top = self.top + 1;

	def pop(self):	# 出栈之前检查栈是否为空
		if self.isempty():
			raise exception("stack is empty");
		else:
			self.top = self.top - 1;
			return self.stack.pop();

	def isfull(self):
		return self.top + 1 == self.size;

	def isempty(self):
		return self.top == -1;
