# -*- coding: utf-8 -*-
# HidenCloud 自动续期 - Python 全日志推送版 (CSRF 419 修复版)
import os
import sys
import time
import json
import random
import re
import requests
import cloudscraper
from bs4 import BeautifulSoup
from urllib.parse import urljoin, unquote

RENEW_DAYS = 7
CACHE_FILE_NAME = 'hiden_cookies.json'
LOCAL_CACHE_PATH = os.path.join(os.path.dirname(__file__), CACHE_FILE_NAME)

ALL_LOGS = []

def log_print(msg):
    print(msg)
    ALL_LOGS.append(str(msg))

def send_notify(text, desp):
    token = os.environ.get("WP_APP_TOKEN_ONE")
    uids_str = os.environ.get("WP_UIDs")
    if not token or not uids_str:
        log_print("⚠️ 未配置 WxPusher，跳过推送")
        return
    log_print(f"\n==== 开始推送通知: {text} ====\n")
    uids = [u.strip() for u in re.split(r'[,;\n]', uids_str) if u.strip()]
    url = 'https://wxpusher.zjiecode.com/api/send/message'
    data = {
        "appToken": token,
        "content": f"<h3>{text}</h3><br><div style='font-size:14px;'>{desp.replace(chr(10), '<br>')}</div>",
        "summary": text,
        "contentType": 2,
        "uids": uids
    }
    try:
        res = requests.post(url, json=data)
        if res.status_code == 200:
            print("✅ WxPusher 推送成功")
        else:
            print(f"❌ WxPusher 推送响应: {res.text}")
    except Exception as e:
        print(f"❌ WxPusher 推送失败: {e}")

class WebDavManager:
    def __init__(self):
        self.url = os.environ.get("WEBDAV_URL", "")
        self.user = os.environ.get("WEBDAV_USER")
        self.password = os.environ.get("WEBDAV_PASS")
        if self.url and not self.url.endswith('/'):
            self.url += '/'
        self.full_url = self.url + CACHE_FILE_NAME if self.url else ""

    def download(self):
        if not self.url or not self.user:
            log_print("⚠️ 未配置 WebDAV，跳过云端同步")
            return
        log_print("☁️ 正在从 Infinicloud 下载缓存...")
        try:
            res = requests.get(self.full_url, auth=(self.user, self.password), timeout=30)
            if res.status_code == 200:
                with open(LOCAL_CACHE_PATH, 'w', encoding='utf-8') as f:
                    f.write(res.text)
                log_print("✅ 云端缓存下载成功")
            elif res.status_code == 404:
                log_print("⚪ 云端暂无缓存文件 (首次运行)")
            else:
                log_print(f"⚠️ 下载失败，状态码: {res.status_code}")
        except Exception as e:
            log_print(f"❌ WebDAV 下载错误: {e}")

    def upload(self, data):
        if not self.url or not self.user:
            return
        log_print("☁️ 正在上传最新缓存到 Infinicloud...")
        try:
            json_str = json.dumps(data, indent=2)
            res = requests.put(
                self.full_url,
                data=json_str,
                auth=(self.user, self.password),
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            if res.status_code in [200, 201, 204]:
                log_print("✅ 云端缓存上传成功")
            else:
                log_print(f"❌ WebDAV 上传失败: {res.status_code}")
        except Exception as e:
            log_print(f"❌ WebDAV 上传错误: {e}")

def sleep_random(min_ms=3000, max_ms=8000):
    sec = random.randint(min_ms, max_ms) / 1000.0
    time.sleep(sec)

class CacheManager:
    @staticmethod
    def load():
        if os.path.exists(LOCAL_CACHE_PATH):
            try:
                with open(LOCAL_CACHE_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                log_print("读取本地缓存失败")
        return {}

    @staticmethod
    def save_local(data):
        """仅保存到本地文件，不触发 WebDAV 上传"""
        with open(LOCAL_CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def update_and_upload(index, cookie_str):
        """保存到本地并上传 WebDAV (仅在关键节点调用)"""
        dav = WebDavManager()
        data = CacheManager.load()
        key = str(index)
        if data.get(key) != cookie_str:
            data[key] = cookie_str
            CacheManager.save_local(data)
            log_print(f"💾 [账号 {index + 1}] 本地缓存已更新")
            dav.upload(data)

    @staticmethod
    def update_local_only(index, cookie_str):
        """仅保存到本地，不触发 WebDAV 上传"""
        data = CacheManager.load()
        key = str(index)
        if data.get(key) != cookie_str:
            data[key] = cookie_str
            CacheManager.save_local(data)

class HidenCloudBot:
    def __init__(self, env_cookie, index):
        self.index = index + 1
        self.base_url = "https://dash.hidencloud.com"
        self.session = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
        )
        # 设置默认请求头，模拟真实浏览器
        self.session.headers.update({
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
        })
        self.csrf_token = ""
        self.services = []
        cached_data = CacheManager.load()
        cached_cookie = cached_data.get(str(index))
        if cached_cookie:
            log_print(f"[账号 {self.index}] 发现本地缓存 Cookie，优先使用...")
            self.load_cookie_str(cached_cookie)
        else:
            log_print(f"[账号 {self.index}] 使用环境变量 Cookie...")
            self.load_cookie_str(env_cookie)

    def log(self, msg):
        log_print(f"[账号 {self.index}] {msg}")

    def load_cookie_str(self, cookie_str):
        if not cookie_str:
            return
        cookie_dict = {}
        for item in cookie_str.split(';'):
            if '=' in item:
                k, v = item.split('=', 1)
                cookie_dict[k.strip()] = v.strip()
        self.session.cookies.update(cookie_dict)

    def get_cookie_str(self):
        return '; '.join([f"{c.name}={c.value}" for c in self.session.cookies])

    def save_cookies_local(self):
        """仅保存到本地 (不触发 WebDAV)"""
        CacheManager.update_local_only(self.index - 1, self.get_cookie_str())

    def save_cookies_full(self):
        """保存到本地并上传 WebDAV (关键节点使用)"""
        CacheManager.update_and_upload(self.index - 1, self.get_cookie_str())

    def reset_to_env(self, env_cookie):
        self.session.cookies.clear()
        self.load_cookie_str(env_cookie)
        self.log("切换回环境变量原始 Cookie 重试...")

    def get_xsrf_header(self):
        """读取 XSRF-TOKEN cookie 并解码，用于 X-XSRF-TOKEN 请求头"""
        xsrf = self.session.cookies.get('XSRF-TOKEN')
        if xsrf:
            return unquote(xsrf)
        return None

    def warmup_session(self):
        """预热会话：先访问首页让 cloudscraper 完成 Cloudflare 挑战"""
        self.log("🔄 预热会话，访问首页以通过 Cloudflare 验证...")
        try:
            res = self.session.get(self.base_url, timeout=30)
            self.log(f"预热完成，状态码: {res.status_code}，URL: {res.url}")
            sleep_random(1000, 2000)
        except Exception as e:
            self.log(f"预热请求异常: {e}")

    def request_get(self, url):
        """发送 GET 请求"""
        full_url = urljoin(self.base_url, url)
        try:
            resp = self.session.get(full_url, timeout=30)
            return resp
        except Exception as e:
            self.log(f"GET 请求异常: {e}")
            raise

    def request_post(self, url, data=None, referer=None):
        """发送 POST 请求，自动附带 AJAX 头和 XSRF-TOKEN"""
        full_url = urljoin(self.base_url, url)
        headers = {
            'X-Requested-With': 'XMLHttpRequest',
            'Origin': 'https://dash.hidencloud.com',
            'Accept': 'text/html, application/json, */*',
        }
        if self.csrf_token:
            headers['X-CSRF-TOKEN'] = self.csrf_token
        xsrf = self.get_xsrf_header()
        if xsrf:
            headers['X-XSRF-TOKEN'] = xsrf
        if referer:
            headers['Referer'] = referer
        try:
            resp = self.session.post(full_url, data=data, headers=headers, timeout=30)
            return resp
        except Exception as e:
            self.log(f"POST 请求异常: {e}")
            raise

    def update_csrf_from_html(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        token_tag = soup.find('meta', attrs={'name': 'csrf-token'})
        if token_tag and token_tag.get('content'):
            self.csrf_token = token_tag['content']
            return True
        self.log("⚠️ 页面中未找到 csrf-token meta 标签")
        return False

    def init(self, retry=0):
        self.log("正在验证登录状态...")
        try:
            res = self.request_get('/dashboard')
            if '/login' in res.url:
                self.log("❌ 当前 Cookie 已失效")
                return False
            soup = BeautifulSoup(res.text, 'html.parser')
            title = soup.title.string if soup.title else '无标题'
            log_print(f"👀 [调试] 网页标题是: {title}")

            if not self.update_csrf_from_html(res.text):
                # 打印页面内容辅助调试
                self.log(f"👀 [调试] 页面响应URL: {res.url}")
                self.log(f"👀 [调试] 页面内容前500字: {res.text[:500]}")
                if retry < 2:
                    self.log(f"🔄 可能是 Cloudflare 挑战页面，{5 + retry * 3}秒后重试 (第{retry+1}次)...")
                    time.sleep(5 + retry * 3)
                    self.warmup_session()
                    return self.init(retry=retry + 1)
                self.log("❌ 多次重试后仍无法获取 CSRF token")
                return False

            self.services = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                if '/service/' in href and '/manage' in href:
                    svc_id = href.split('/service/')[1].split('/')[0]
                    if not any(s['id'] == svc_id for s in self.services):
                        self.services.append({'id': svc_id, 'url': href})

            self.log(f"✅ 登录成功，发现 {len(self.services)} 个服务。")
            # 登录验证成功后，保存一次 cookies 到本地 + WebDAV
            self.save_cookies_full()
            return True
        except Exception as e:
            self.log(f"❌ 初始化异常: {e}")
            return False

    def process_service(self, service):
        sleep_random(2000, 4000)
        self.log(f">>> 处理服务 ID: {service['id']}")
        try:
            self.check_and_pay_invoices(service['id'], is_precheck=True)

            manage_res = self.request_get(f"/service/{service['id']}/manage")
            soup = BeautifulSoup(manage_res.text, 'html.parser')

            # 从 manage 页面刷新 CSRF token
            if not self.update_csrf_from_html(manage_res.text):
                self.log("⚠️ manage 页面未找到 CSRF token，尝试继续...")

            renew_btn = soup.find('button', onclick=re.compile(r'showRenewAlert'))
            if renew_btn:
                onclick_val = renew_btn['onclick']
                match = re.search(r'showRenewAlert\((\d+),\s*(\d+),\s*(true|false)\)', onclick_val)
                if match:
                    days_until = int(match.group(1))
                    threshold = int(match.group(2))
                    is_free = match.group(3) == 'true'
                    if days_until > threshold:
                        threshold_text = "1 day" if threshold == 1 else f"{threshold} days"
                        if is_free:
                            msg = f"免费服务剩余时间低于 {threshold_text} 才可续期。当前剩余: {days_until} 天。"
                        else:
                            msg = f"剩余时间低于 {threshold_text} 才可续期。当前剩余: {days_until} 天。"
                        self.log(f"⏳ 暂未到达续期时间: {msg}")
                        return

            token_input = soup.find('input', attrs={'name': '_token'})
            if not token_input:
                self.log("❌ 无法找到续期 Token (可能是服务已到期或页面结构变更)")
                return

            form_token = token_input['value']
            # 确保 _token 和 csrf_token 一致
            if self.csrf_token and form_token != self.csrf_token:
                self.log(f"⚠️ form _token 与 meta csrf-token 不一致，使用 meta csrf-token")
                form_token = self.csrf_token

            self.log(f"提交续期 ({RENEW_DAYS}天)...")
            sleep_random(1000, 2000)

            referer_url = f"https://dash.hidencloud.com/service/{service['id']}/manage"
            payload = {'_token': form_token, 'days': RENEW_DAYS}

            res = self.request_post(
                f"/service/{service['id']}/renew",
                data=payload,
                referer=referer_url
            )

            # 419 时重新获取 token 并重试
            if res.status_code == 419:
                self.log(f"⚠️ CSRF token 不匹配 (419)，响应内容前500字: {res.text[:500]}")
                self.log("🔄 重新访问 manage 页面获取新 token 并重试...")
                sleep_random(2000, 4000)

                manage_res2 = self.request_get(f"/service/{service['id']}/manage")
                if not self.update_csrf_from_html(manage_res2.text):
                    self.log("❌ 重试失败：无法获取新的 CSRF token")
                    return

                soup2 = BeautifulSoup(manage_res2.text, 'html.parser')
                token_input2 = soup2.find('input', attrs={'name': '_token'})
                new_token = self.csrf_token  # 使用 meta 中的 token
                if token_input2:
                    new_token = token_input2['value']

                payload['_token'] = new_token
                res = self.request_post(
                    f"/service/{service['id']}/renew",
                    data=payload,
                    referer=referer_url
                )

            if res.status_code == 419:
                self.log(f"❌ 重试仍然 419，可能需要重新登录。响应: {res.text[:500]}")
                return

            if '/invoice/' in res.url:
                self.log("⚡️ 续期成功，已跳转账单页，自动执行支付...")
                self.perform_pay_from_html(res.text, res.url)
            elif res.status_code == 200 or res.status_code == 302:
                soup_resp = BeautifulSoup(res.text, 'html.parser')
                for a in soup_resp.find_all('a', href=True):
                    if '/invoice/' in a['href']:
                        self.log(f"🔗 在响应HTML中发现账单链接: {a['href']}")
                        self.pay_single_invoice(a['href'])
                        return
                # 检查是否有成功提示
                success_div = soup_resp.find('div', class_=re.compile(r'(alert-success|text-success)'))
                if success_div:
                    self.log(f"✅ 续期请求已提交: {success_div.get_text(strip=True)}")
                else:
                    err_div = soup_resp.find('div', class_=re.compile(r'(alert-danger|text-danger|error)'))
                    if err_div:
                        self.log(f"⚠️ 续期请求被服务端拒绝，页面提示: {err_div.get_text(strip=True)}")
                    else:
                        self.log(f"⚠️ 提交后未自动跳转，响应URL: {res.url} | 状态码: {res.status_code}")
                        self.log("后置轮询检查账单...")
                        self.check_and_pay_invoices(service['id'], is_precheck=False, retries=3)
            else:
                self.log(f"⚠️ 意外的响应状态码: {res.status_code}")
                self.log("后置轮询检查账单...")
                self.check_and_pay_invoices(service['id'], is_precheck=False, retries=3)
        except Exception as e:
            self.log(f"处理异常: {e}")

    def check_and_pay_invoices(self, service_id, is_precheck=False, retries=1):
        if not is_precheck:
            sleep_random(2000, 3000)
        for attempt in range(retries):
            try:
                res = self.request_get(f"/service/{service_id}/invoices?where=unpaid")
                soup = BeautifulSoup(res.text, 'html.parser')
                invoice_links = []
                for a in soup.find_all('a', href=True):
                    if '/invoice/' in a['href'] and 'download' not in a['href']:
                        invoice_links.append(a['href'])
                unique_invoices = list(set(invoice_links))
                if not unique_invoices:
                    if retries > 1 and attempt < retries - 1:
                        self.log(f"⚪ 第{attempt+1}次检查无账单，5秒后重试...")
                        time.sleep(5)
                        continue
                    if not is_precheck:
                        self.log("⚪ 无未支付账单")
                    return
                self.log(f"🔍 发现 {len(unique_invoices)} 个未付账单，准备清理...")
                for url in unique_invoices:
                    self.pay_single_invoice(url)
                    sleep_random(3000, 5000)
                return
            except Exception as e:
                self.log(f"查账单出错: {e}")
                return

    def pay_single_invoice(self, url):
        try:
            self.log(f"📄 打开账单: {url}")
            res = self.request_get(url)
            self.perform_pay_from_html(res.text, url)
        except Exception as e:
            self.log(f"访问账单失败: {e}")

    def perform_pay_from_html(self, html_content, current_url):
        soup = BeautifulSoup(html_content, 'html.parser')
        # 从账单页刷新 CSRF token
        self.update_csrf_from_html(html_content)
        target_form = None
        target_action = ""
        for form in soup.find_all('form'):
            btn = form.find('button')
            if btn and 'pay' in btn.get_text().lower():
                action = form.get('action', '')
                if action and 'balance/add' not in action:
                    target_form = form
                    target_action = action
                    break
        if not target_form:
            self.log("⚪ 页面未找到支付表单 (可能已支付)。")
            return
        payload = {}
        for inp in target_form.find_all('input'):
            name = inp.get('name')
            value = inp.get('value', '')
            if name:
                payload[name] = value
        self.log("👉 提交支付...")
        try:
            res = self.request_post(target_action, data=payload, referer=current_url)
            if res.status_code == 200:
                self.log("✅ 支付成功！")
            else:
                self.log(f"⚠️ 支付响应: {res.status_code}")
        except Exception as e:
            self.log(f"❌ 支付失败: {e}")

if __name__ == '__main__':
    env_cookies = os.environ.get("HIDEN_COOKIE", "")
    cookies_list = re.split(r'[&\n]', env_cookies)
    cookies_list = [c for c in cookies_list if c.strip()]
    if not cookies_list:
        log_print("❌ 未配置环境变量 HIDEN_COOKIE")
        sys.exit(0)
    WebDavManager().download()
    log_print(f"\n=== HidenCloud 续期脚本启动 (Python版 - CSRF修复) ===")
    for i, cookie in enumerate(cookies_list):
        bot = HidenCloudBot(cookie, i)
        # 先预热会话以通过 Cloudflare
        bot.warmup_session()
        success = bot.init()
        if not success:
            bot.reset_to_env(cookie)
            bot.warmup_session()
            success = bot.init()
        if success:
            for service in bot.services:
                bot.process_service(service)
            # 每个账号处理完毕后，统一保存一次 cookies 到 WebDAV
            bot.save_cookies_full()
        else:
            log_print(f"账号 {i + 1}: 登录失败，请检查 Cookie")
        log_print("\n----------------------------------------\n")
        if i < len(cookies_list) - 1:
            sleep_random(5000, 10000)
    final_content = "\n".join(ALL_LOGS)
    if final_content:
        send_notify("HidenCloud 续期报告", final_content)
