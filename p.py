import os
import requests
import json
import time
import random
import schedule
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys

load_dotenv()

class TeaFiAutoClaim:
    def __init__(self):
        self.base_url = "https://api.tea-fi.com"
        self.wallets = self.load_wallets()
        self.proxies_list = self.load_proxies_list()
        self.session = requests.Session()
        
        # Headers sesuai dengan request yang ditangkap
        self.headers = {
            'Accept': 'application/json, text/plain, */*',
            'Origin': 'https://app.tea-fi.com',
            'Referer': 'https://app.tea-fi.com/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
            'Sec-Ch-Ua': '"Brave";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
            'Sec-Gpc': '1',
            'Priority': 'u=1, i'
        }
        
        # Config
        self.claim_delay = int(os.getenv('CLAIM_DELAY', 5))
        self.max_workers = int(os.getenv('MAX_WORKERS', 3))
        self.retry_count = int(os.getenv('RETRY_COUNT', 2))
        self.daily_run_time = os.getenv('DAILY_RUN_TIME', '00:01')  # Waktu run harian
        self.auto_restart = os.getenv('AUTO_RESTART', 'true').lower() == 'true'
        
        # Statistics
        self.stats = {
            'total_runs': 0,
            'total_success': 0,
            'total_points': 0,
            'last_run': None,
            'next_run': None
        }
    
    def load_wallets(self):
        """Load wallet addresses dari environment variable"""
        wallets_str = os.getenv('WALLETS', '')
        wallets = [wallet.strip() for wallet in wallets_str.split(',') if wallet.strip()]
        print(f"ðŸ“¥ Loaded {len(wallets)} wallets")
        return wallets
    
    def load_proxies_list(self):
        """Load multiple proxies dari environment variable"""
        proxies_str = os.getenv('PROXIES', '')
        if not proxies_str:
            return []
        
        proxies = [proxy.strip() for proxy in proxies_str.split(',') if proxy.strip()]
        
        # Format proxies
        formatted_proxies = []
        for proxy in proxies:
            if not proxy.startswith('http'):
                proxy = f'http://{proxy}'
            formatted_proxies.append({
                'http': proxy,
                'https': proxy
            })
        
        print(f"ðŸ”Œ Loaded {len(formatted_proxies)} proxies")
        return formatted_proxies
    
    def get_proxy_for_wallet(self, wallet_index):
        """Dapatkan proxy untuk wallet tertentu (rotasi)"""
        if not self.proxies_list:
            return None
        
        # Rotasi proxy berdasarkan index wallet
        proxy_index = wallet_index % len(self.proxies_list)
        return self.proxies_list[proxy_index]
    
    def get_current_checkin_status(self, wallet_address, proxy=None):
        """Cek status check-in terakhir untuk wallet"""
        url = f"{self.base_url}/wallet/check-in/current"
        params = {'address': wallet_address}
        
        try:
            if proxy:
                response = self.session.get(url, params=params, headers=self.headers, 
                                          proxies=proxy, timeout=30)
            else:
                response = self.session.get(url, params=params, headers=self.headers, timeout=30)
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"âŒ Gagal cek status untuk {wallet_address[:8]}...: HTTP {response.status_code}")
                return None
                
        except Exception as e:
            print(f"âŒ Error cek status untuk {wallet_address[:8]}...: {str(e)}")
            return None
    
    def is_already_checked_in_today(self, wallet_data):
        """Cek apakah wallet sudah check-in hari ini"""
        if not wallet_data:
            return False
        
        try:
            last_checkin = wallet_data.get('lastCheckIn')
            current_day = wallet_data.get('currentDay', {})
            
            # Jika tidak ada data lastCheckIn, berarti belum pernah check-in
            if not last_checkin:
                return False
            
            # Jika tidak ada data currentDay, gunakan tanggal hari ini
            if not current_day:
                current_date = datetime.now(timezone.utc).date().isoformat()
            else:
                current_date = current_day.get('start', '').split('T')[0]
            
            last_checkin_date = last_checkin.split('T')[0]
            
            return last_checkin_date == current_date
            
        except Exception as e:
            print(f"âš ï¸  Warning parsing date: {e}")
            return False
    
    def perform_checkin(self, wallet_address, proxy=None, retry=0):
        """Melakukan check-in untuk wallet dengan retry mechanism"""
        url = f"{self.base_url}/wallet/check-in"
        params = {'address': wallet_address}
        
        try:
            if proxy:
                response = self.session.post(url, params=params, headers=self.headers, 
                                           proxies=proxy, timeout=30)
            else:
                response = self.session.post(url, params=params, headers=self.headers, timeout=30)
            
            if response.status_code == 201:
                result = response.json()
                return {
                    'success': True,
                    'points': result.get('points', 0),
                    'issued_day': result.get('issuedDay', 'N/A'),
                    'wallet': wallet_address
                }
            else:
                error_msg = f"HTTP {response.status_code}"
                if response.text:
                    try:
                        error_data = response.json()
                        error_msg = error_data.get('message', error_msg)
                    except:
                        error_msg = response.text[:100]
                
                # Retry logic
                if retry < self.retry_count:
                    delay = (retry + 1) * 2  # Exponential backoff
                    print(f"   ðŸ”„ Retry {retry + 1}/{self.retry_count} dalam {delay} detik...")
                    time.sleep(delay)
                    return self.perform_checkin(wallet_address, proxy, retry + 1)
                
                return {
                    'success': False,
                    'error': error_msg,
                    'wallet': wallet_address
                }
                
        except Exception as e:
            error_msg = str(e)
            # Retry logic untuk network errors
            if retry < self.retry_count:
                delay = (retry + 1) * 2
                print(f"   ðŸ”„ Retry {retry + 1}/{self.retry_count} dalam {delay} detik...")
                time.sleep(delay)
                return self.perform_checkin(wallet_address, proxy, retry + 1)
            
            return {
                'success': False,
                'error': error_msg,
                'wallet': wallet_address
            }
    
    def get_wallet_info(self, wallet_data):
        """Mendapatkan informasi wallet dengan error handling"""
        if not wallet_data:
            return "Tidak ada data"
        
        info = []
        try:
            if 'streak' in wallet_data:
                info.append(f"Streak: {wallet_data['streak']} hari")
            
            if 'totalPoints' in wallet_data:
                info.append(f"Total Points: {wallet_data['totalPoints']}")
            
            # Handle lastCheckIn yang mungkin null
            last_checkin = wallet_data.get('lastCheckIn')
            if last_checkin:
                info.append(f"Last Check-in: {last_checkin.split('T')[0]}")
            else:
                info.append("Last Check-in: Never")
                
        except Exception as e:
            info.append(f"Error reading data: {str(e)}")
        
        return ", ".join(info) if info else "No information available"
    
    def process_single_wallet(self, wallet_data):
        """Process single wallet untuk threading"""
        wallet, index = wallet_data
        proxy = self.get_proxy_for_wallet(index)
        
        print(f"\n[{index + 1}/{len(self.wallets)}] Processing: {wallet[:10]}...{wallet[-6:]}")
        if proxy:
            proxy_display = proxy['http']
            if '@' in proxy_display:
                proxy_display = proxy_display.split('@')[-1]
            print(f"   ðŸ”Œ Using proxy: {proxy_display}")
        
        # Cek status saat ini
        wallet_info = self.get_current_checkin_status(wallet, proxy)
        
        if wallet_info is None:
            return {'status': 'failed', 'wallet': wallet, 'message': 'Gagal mendapatkan data'}
        
        print(f"   ðŸ“Š {self.get_wallet_info(wallet_info)}")
        
        # Cek apakah sudah check-in hari ini
        if self.is_already_checked_in_today(wallet_info):
            return {'status': 'skipped', 'wallet': wallet, 'message': 'Sudah check-in hari ini'}
        
        # Hitung waktu tunggu berdasarkan index (staggered timing)
        wait_time = index * self.claim_delay
        if wait_time > 0:
            print(f"   â° Menunggu {wait_time} detik sebelum claim...")
            for i in range(wait_time, 0, -1):
                print(f"   ðŸ•’ {i}...", end='\r', flush=True)
                time.sleep(1)
            print("   ðŸš€ Memulai claim...")
        
        # Lakukan check-in
        result = self.perform_checkin(wallet, proxy)
        
        if result['success']:
            print(f"   âœ… Check-in berhasil!")
            print(f"   ðŸŽ Points earned: {result['points']}")
            print(f"   ðŸ“… Issued: {result['issued_day']}")
            return {
                'status': 'success', 
                'wallet': wallet, 
                'points': result['points'],
                'issued_day': result['issued_day']
            }
        else:
            print(f"   âŒ Gagal check-in: {result['error']}")
            return {'status': 'failed', 'wallet': wallet, 'message': result['error']}
    
    def run_sequential_claim(self):
        """Menjalankan claim secara sequential dengan timing teratur"""
        if not self.wallets:
            print("âŒ Tidak ada wallet yang dikonfigurasi!")
            return
        
        print(f"ðŸš€ Memulai Sequential Auto Claim Tea-Fi")
        print(f"ðŸ“Š Total: {len(self.wallets)} wallet(s)")
        print(f"ðŸ”Œ Proxies: {len(self.proxies_list)} available")
        print(f"â° Delay antar wallet: {self.claim_delay} detik")
        print(f"ðŸ”„ Max retry: {self.retry_count}")
        print("-" * 60)
        
        results = {
            'success': 0,
            'skipped': 0,
            'failed': 0,
            'details': []
        }
        
        start_time = datetime.now()
        
        for i, wallet in enumerate(self.wallets):
            result = self.process_single_wallet((wallet, i))
            results['details'].append(result)
            
            if result['status'] == 'success':
                results['success'] += 1
            elif result['status'] == 'skipped':
                results['skipped'] += 1
            else:
                results['failed'] += 1
        
        # Summary
        self.print_summary(results, start_time)
        
        # Update statistics
        self.update_stats(results)
        return results
    
    def run_parallel_claim(self):
        """Menjalankan claim secara parallel dengan thread pool"""
        if not self.wallets:
            print("âŒ Tidak ada wallet yang dikonfigurasi!")
            return
        
        print(f"ðŸš€ Memulai Parallel Auto Claim Tea-Fi")
        print(f"ðŸ“Š Total: {len(self.wallets)} wallet(s)")
        print(f"ðŸ”Œ Proxies: {len(self.proxies_list)} available")
        print(f"ðŸ§µ Workers: {self.max_workers}")
        print(f"ðŸ”„ Max retry: {self.retry_count}")
        print("-" * 60)
        
        results = {
            'success': 0,
            'skipped': 0,
            'failed': 0,
            'details': []
        }
        
        start_time = datetime.now()
        
        # Prepare wallet data dengan index
        wallet_data = [(wallet, i) for i, wallet in enumerate(self.wallets)]
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_wallet = {
                executor.submit(self.process_single_wallet, data): data 
                for data in wallet_data
            }
            
            for future in as_completed(future_to_wallet):
                try:
                    result = future.result()
                    results['details'].append(result)
                    
                    if result['status'] == 'success':
                        results['success'] += 1
                    elif result['status'] == 'skipped':
                        results['skipped'] += 1
                    else:
                        results['failed'] += 1
                        
                except Exception as e:
                    wallet_data = future_to_wallet[future]
                    print(f"âŒ Exception untuk wallet {wallet_data[0][:8]}...: {str(e)}")
                    results['failed'] += 1
                    results['details'].append({
                        'status': 'failed', 
                        'wallet': wallet_data[0], 
                        'message': str(e)
                    })
        
        # Summary
        self.print_summary(results, start_time)
        
        # Update statistics
        self.update_stats(results)
        return results
    
    def print_summary(self, results, start_time):
        """Print summary hasil claim"""
        end_time = datetime.now()
        duration = end_time - start_time
        
        print("\n" + "=" * 60)
        print("ðŸ“Š CLAIM SUMMARY:")
        print("=" * 60)
        print(f"âœ… Berhasil check-in: {results['success']} wallet(s)")
        print(f"â­ï¸  Sudah check-in: {results['skipped']} wallet(s)")
        print(f"âŒ Gagal: {results['failed']} wallet(s)")
        print(f"â±ï¸  Durasi: {duration}")
        print(f"ðŸ•’ Waktu selesai: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Detail points untuk yang berhasil
        successful_claims = [r for r in results['details'] if r['status'] == 'success']
        if successful_claims:
            total_points = sum(r.get('points', 0) for r in successful_claims)
            print(f"ðŸ’° Total points didapat: {total_points}")
        
        print("\nðŸ“ Detail:")
        for result in results['details']:
            status_icon = "âœ…" if result['status'] == 'success' else "â­ï¸" if result['status'] == 'skipped' else "âŒ"
            wallet_short = f"{result['wallet'][:10]}...{result['wallet'][-6:]}"
            if result['status'] == 'success':
                print(f"  {status_icon} {wallet_short} - {result['points']} points")
            else:
                print(f"  {status_icon} {wallet_short} - {result.get('message', 'Unknown error')}")
    
    def update_stats(self, results):
        """Update statistics setelah setiap run"""
        self.stats['total_runs'] += 1
        self.stats['last_run'] = datetime.now()
        
        successful_claims = [r for r in results['details'] if r['status'] == 'success']
        points_this_run = sum(r.get('points', 0) for r in successful_claims)
        
        self.stats['total_success'] += results['success']
        self.stats['total_points'] += points_this_run
        
        # Calculate next run time
        if self.daily_run_time:
            now = datetime.now()
            run_hour, run_minute = map(int, self.daily_run_time.split(':'))
            next_run = now.replace(hour=run_hour, minute=run_minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            self.stats['next_run'] = next_run
    
    def show_stats(self):
        """Show cumulative statistics"""
        print("\n" + "=" * 60)
        print("ðŸ“ˆ CUMULATIVE STATISTICS:")
        print("=" * 60)
        print(f"ðŸ”„ Total Runs: {self.stats['total_runs']}")
        print(f"âœ… Total Successful Claims: {self.stats['total_success']}")
        print(f"ðŸ’° Total Points Collected: {self.stats['total_points']}")
        if self.stats['last_run']:
            print(f"ðŸ•’ Last Run: {self.stats['last_run'].strftime('%Y-%m-%d %H:%M:%S')}")
        if self.stats['next_run']:
            print(f"â° Next Run: {self.stats['next_run'].strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
    
    def run_daily_scheduler(self):
        """Menjalankan scheduler harian"""
        print("ðŸ”„ Starting Daily Auto Claim Scheduler...")
        print(f"â° Daily run time: {self.daily_run_time}")
        print(f"ðŸ”§ Auto restart: {self.auto_restart}")
        print("ðŸ’¡ Press Ctrl+C to stop the scheduler")
        print("-" * 60)
        
        # Show initial stats
        self.show_stats()
        
        # Schedule daily job
        schedule.every().day.at(self.daily_run_time).do(self.run_scheduled_claim)
        
        # Check if we should run immediately on startup
        if os.getenv('RUN_ON_STARTUP', 'true').lower() == 'true':
            print("\nðŸš€ Running initial claim on startup...")
            self.run_scheduled_claim()
        
        # Main scheduler loop
        while True:
            try:
                # Check for pending jobs
                next_run = schedule.next_run()
                if next_run:
                    wait_seconds = (next_run - datetime.now()).total_seconds()
                    if wait_seconds > 0:
                        print(f"\nâ° Next run scheduled at: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
                        print(f"ðŸ’¤ Sleeping for {wait_seconds:.0f} seconds...")
                        
                        # Countdown display
                        while wait_seconds > 0:
                            hours = int(wait_seconds // 3600)
                            minutes = int((wait_seconds % 3600) // 60)
                            seconds = int(wait_seconds % 60)
                            
                            if wait_seconds > 3600:
                                print(f"   ðŸ•’ Next run in: {hours:02d}:{minutes:02d}:{seconds:02d}", end='\r', flush=True)
                            else:
                                print(f"   ðŸ•’ Next run in: {minutes:02d}:{seconds:02d}", end='\r', flush=True)
                            
                            time.sleep(1)
                            wait_seconds -= 1
                        
                        print("\n" + "=" * 60)
                
                # Run pending jobs
                schedule.run_pending()
                time.sleep(1)
                
            except KeyboardInterrupt:
                print("\n\nðŸ‘‹ Shutting down scheduler...")
                self.show_stats()
                print("âœ… Scheduler stopped successfully!")
                break
            except Exception as e:
                print(f"\nâš ï¸ Error in scheduler: {str(e)}")
                if self.auto_restart:
                    print("ðŸ”„ Auto-restarting in 60 seconds...")
                    time.sleep(60)
                else:
                    print("âŒ Scheduler stopped due to error!")
                    break
    
    def run_scheduled_claim(self):
        """Run claim untuk scheduler"""
        print(f"\nðŸŽ¯ Scheduled Claim Started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        
        try:
            mode = os.getenv('CLAIM_MODE', 'sequential').lower()
            if mode == 'parallel':
                results = self.run_parallel_claim()
            else:
                results = self.run_sequential_claim()
            
            # Show updated stats
            self.show_stats()
            
            return results
            
        except Exception as e:
            print(f"âŒ Error during scheduled claim: {str(e)}")
            import traceback
            traceback.print_exc()
            return None

def main():
    """Fungsi utama"""
    auto_claim = TeaFiAutoClaim()
    
    # Check if daily mode is enabled
    daily_mode = os.getenv('DAILY_MODE', 'false').lower() == 'true'
    
    if daily_mode:
        # Run in daily scheduler mode
        auto_claim.run_daily_scheduler()
    else:
        # Single run mode
        mode = os.getenv('CLAIM_MODE', 'sequential').lower()
        if mode == 'parallel':
            auto_claim.run_parallel_claim()
        else:
            auto_claim.run_sequential_claim()
        
        # Show stats for single run
        auto_claim.show_stats()

if __name__ == "__main__":
    main()
