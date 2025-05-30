#!/usr/bin/env python3
import unittest
from unittest.mock import patch, mock_open, MagicMock
import asyncio
from datetime import datetime, timedelta, time
import sys
import json
from pathlib import Path

# 프로젝트 루트 디렉토리를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from flight_checker import (
    validate_url,
    parse_flight_info,
    check_time_restrictions,
    valid_date,
    valid_airport,
    get_user_config,
    save_user_config,
    format_time_range,
    get_time_range,
    MessageManager,
    DEFAULT_USER_CONFIG,
    TIME_PERIODS,
    format_datetime
)

# flight_checker.logger를 모킹하여 테스트 중 로그 출력 방지
# 실제 로깅 테스트가 필요한 경우 다르게 처리해야 함
@patch('flight_checker.logger', MagicMock())
class TestFlightChecker(unittest.TestCase):
    def setUp(self):
        # 테스트용 사용자 ID
        self.test_user_id = 12345
        # MessageManager 인스턴스 생성
        self.message_manager = MessageManager()
        # get_user_config 등에서 USER_CONFIG_DIR을 사용하므로, 모킹 준비
        self.user_config_dir_patcher = patch('flight_checker.USER_CONFIG_DIR', Path('/tmp/test_user_configs'))
        self.mock_user_config_dir = self.user_config_dir_patcher.start()
        self.mock_user_config_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.user_config_dir_patcher.stop()
        # 테스트 후 생성된 임시 파일/디렉토리 정리 (필요시)
        config_file = self.mock_user_config_dir / f"config_{self.test_user_id}.json"
        if config_file.exists():
            config_file.unlink()
        if self.mock_user_config_dir.exists() and not list(self.mock_user_config_dir.iterdir()):
             self.mock_user_config_dir.rmdir()

    def test_validate_url(self):
        """URL 검증 테스트"""
        valid_urls = [
            "http://localhost:4444/wd/hub",
            "https://example.com/path",
            "http://127.0.0.1:8080"
        ]
        invalid_urls = [
            "ftp://example.com",
            "not_a_url",
            "http:/missing-slash",
            ""
        ]
        
        for url in valid_urls:
            is_valid, _ = validate_url(url)
            self.assertTrue(is_valid, f"URL should be valid: {url}")
            
        for url in invalid_urls:
            is_valid, _ = validate_url(url)
            self.assertFalse(is_valid, f"URL should be invalid: {url}")
            
    def test_parse_flight_info(self):
        """항공편 정보 파싱 테스트"""
        # 유효한 항공편 정보
        valid_text = """
        07:00ICN 09:00FUK
        15:00FUK 17:00ICN
        왕복 374,524원
        """
        result = parse_flight_info(valid_text, "ICN", "FUK")
        self.assertIsNotNone(result)
        dep_time, dep_arr, ret_time, ret_arr, price = result
        self.assertEqual(dep_time, "07:00")
        self.assertEqual(ret_time, "15:00")
        self.assertEqual(price, 374524)
        
        # 잘못된 형식
        invalid_text = "Invalid flight info"
        result = parse_flight_info(invalid_text, "ICN", "FUK")
        self.assertIsNone(result)
        
    def test_check_time_restrictions(self):
        """시간 제한 체크 테스트"""
        # 시간대 설정 테스트
        period_config = {
            "time_type": "time_period",
            "outbound_periods": ["오전1"],  # 06:00-09:00
            "inbound_periods": ["오후1"]    # 12:00-15:00
        }
        
        # 유효한 시간
        self.assertTrue(
            check_time_restrictions("07:00", "13:00", period_config),
            "Valid time period should be accepted"
        )
        
        # 유효하지 않은 시간
        self.assertFalse(
            check_time_restrictions("10:00", "13:00", period_config),
            "Invalid outbound time should be rejected"
        )
        self.assertFalse(
            check_time_restrictions("07:00", "16:00", period_config),
            "Invalid inbound time should be rejected"
        )
        
        # 시각 설정 테스트
        exact_config = {
            "time_type": "exact",
            "outbound_exact_hour": 9,
            "inbound_exact_hour": 15
        }
        
        # 유효한 시간
        self.assertTrue(
            check_time_restrictions("08:00", "16:00", exact_config),
            "Valid exact time should be accepted"
        )
        
        # 유효하지 않은 시간
        self.assertFalse(
            check_time_restrictions("10:00", "16:00", exact_config),
            "Invalid outbound time should be rejected"
        )
        self.assertFalse(
            check_time_restrictions("08:00", "14:00", exact_config),
            "Invalid inbound time should be rejected"
        )
        
    def test_valid_date(self):
        """날짜 유효성 검사 테스트"""
        today = datetime.now()
        future_date = (today + timedelta(days=30)).strftime("%Y%m%d")
        past_date = (today - timedelta(days=1)).strftime("%Y%m%d")
        far_future = (today + timedelta(days=400)).strftime("%Y%m%d")
        
        # 유효한 날짜
        is_valid, _ = valid_date(future_date)
        self.assertTrue(is_valid, "Future date should be valid")
        
        # 과거 날짜
        is_valid, _ = valid_date(past_date)
        self.assertFalse(is_valid, "Past date should be invalid")
        
        # 1년 이상 미래
        is_valid, _ = valid_date(far_future)
        self.assertFalse(is_valid, "Far future date should be invalid")
        
        # 잘못된 형식
        is_valid, _ = valid_date("invalid")
        self.assertFalse(is_valid, "Invalid format should be rejected")
        
    def test_valid_airport(self):
        """공항 코드 유효성 검사 테스트"""
        # 유효한 공항 코드
        is_valid, _ = valid_airport("ICN")
        self.assertTrue(is_valid, "Valid airport code should be accepted")
        
        # 잘못된 형식
        is_valid, _ = valid_airport("INVALID")
        self.assertFalse(is_valid, "Invalid airport code should be rejected")
        is_valid, _ = valid_airport("12")
        self.assertFalse(is_valid, "Invalid airport code should be rejected")

    @patch('flight_checker.save_json_data') # save_user_config 내부의 save_json_data 모킹
    @patch('flight_checker.load_json_data') # get_user_config 내부의 load_json_data 모킹
    def test_get_and_save_user_config(self, mock_load_json_data, mock_save_json_data):
        """사용자 설정 로드 및 저장 테스트"""
        # 1. 기본 설정 생성 및 저장 테스트
        # 파일이 존재하지 않는 경우를 시뮬레이션 (FileNotFoundError 발생시키도록 설정)
        mock_load_json_data.side_effect = FileNotFoundError
        
        # get_user_config 호출 시, 파일이 없으므로 기본 설정이 생성되고 저장되어야 함
        # (내부적으로 save_json_data가 호출될 것이지만, 여기서는 get_user_config의 반환값과
        #  save_json_data가 올바른 인자로 호출되었는지만 확인)
        
        # config_file.exists()가 False를 반환하도록 mock_open 설정
        config_file_path = self.mock_user_config_dir / f"config_{self.test_user_id}.json"
        
        with patch.object(Path, 'exists', return_value=False), \
             patch.object(Path, 'read_text', side_effect=FileNotFoundError), \
             patch('builtins.open', new_callable=mock_open) as mock_file_open:

            config = get_user_config(self.test_user_id)
            
            self.assertIsNotNone(config)
            self.assertEqual(config['time_type'], DEFAULT_USER_CONFIG['time_type'])
            self.assertIsNotNone(config.get('created_at'))
            self.assertIsNotNone(config.get('last_activity'))

            # 기본 설정 저장 시 write_text가 호출되었는지 확인
            # 실제 저장은 save_json_data가 담당하므로, get_user_config 내의 직접적인 write_text 호출 확인
            # 여기서는 save_json_data가 호출될 것이므로 그쪽을 검증
            # get_user_config가 기본 설정을 만들 때 내부적으로 파일 쓰기를 시도함
            # 이 부분을 file_lock과 함께 모킹해야 정확한 테스트가 가능하나, 복잡성을 고려하여
            # 여기서는 save_json_data 모킹으로 대체하여 save_user_config 테스트에 집중

        # 2. 기존 설정 로드 테스트
        # 파일이 존재하는 경우를 시뮬레이션
        saved_config_data = DEFAULT_USER_CONFIG.copy()
        saved_config_data['outbound_periods'] = ["오후1"]
        saved_config_data['created_at'] = format_datetime(datetime.now() - timedelta(days=1))
        saved_config_data['last_activity'] = format_datetime(datetime.now() - timedelta(hours=1))

        # load_json_data가 saved_config_data를 반환하도록 설정
        mock_load_json_data.side_effect = None # 이전 side_effect 제거
        mock_load_json_data.return_value = saved_config_data
        
        # config_file.exists()가 True를 반환하도록 mock_open 설정
        with patch.object(Path, 'exists', return_value=True), \
             patch('builtins.open', mock_open(read_data=json.dumps(saved_config_data))) as mock_file_open_read:
            
            loaded_config = get_user_config(self.test_user_id)
        
        self.assertEqual(loaded_config['outbound_periods'], ["오후1"])
        self.assertIsNotNone(loaded_config.get('last_activity')) # last_activity 업데이트 확인
        
        # config_file.write_text가 호출되어 last_activity가 업데이트되었는지 확인
        # (get_user_config 내부의 로직)
        # 이 부분도 file_lock과 json.dump를 모킹해야 정확하지만, 일단 넘어감
        
        # 3. 설정 변경 및 저장 테스트
        new_config = loaded_config.copy()
        new_config['time_type'] = 'exact'
        new_config['outbound_exact_hour'] = 10
        
        save_user_config(self.test_user_id, new_config)
        
        # save_json_data가 올바른 인자와 함께 호출되었는지 확인
        mock_save_json_data.assert_called_once()
        args, _ = mock_save_json_data.call_args
        saved_file_path, saved_data = args
        
        self.assertEqual(saved_file_path, config_file_path)
        self.assertEqual(saved_data['time_type'], 'exact')
        self.assertEqual(saved_data['outbound_exact_hour'], 10)
        self.assertIsNotNone(saved_data.get('last_activity')) # last_activity 업데이트 확인
        self.assertIsNotNone(saved_data.get('created_at')) # created_at 유지 확인

    def test_format_time_range(self):
        """시간 설정 문자열 변환 테스트"""
        # 시간대 설정
        period_config = {
            "time_type": "time_period",
            "outbound_periods": ["오전1", "오전2"], # 06-09, 09-12
            "inbound_periods": ["오후2", "밤1"]    # 15-18, 18-21
        }
        self.assertEqual(
            format_time_range(period_config, 'outbound'),
            "오전1, 오전2 (06:00-12:00)"
        )
        self.assertEqual(
            format_time_range(period_config, 'inbound'),
            "오후2, 밤1 (15:00-18:00 / 18:00-21:00)"
        )
        
        # 시각 설정
        exact_config = {
            "time_type": "exact",
            "outbound_exact_hour": 8,
            "inbound_exact_hour": 17
        }
        self.assertEqual(
            format_time_range(exact_config, 'outbound'),
            "08:00 이전"
        )
        self.assertEqual(
            format_time_range(exact_config, 'inbound'),
            "17:00 이후"
        )

    def test_get_time_range(self):
        """시간 범위 반환 테스트"""
        # 시간대 설정 (get_time_range는 period일 때 None, None을 반환함)
        period_config = {
            "time_type": "time_period",
            "outbound_periods": ["오전1"],
            "inbound_periods": ["오후1"]
        }
        start_time, end_time = get_time_range(period_config, 'outbound')
        self.assertIsNone(start_time)
        self.assertIsNone(end_time)
        
        start_time, end_time = get_time_range(period_config, 'inbound')
        self.assertIsNone(start_time)
        self.assertIsNone(end_time)
        
        # 시각 설정
        exact_config = {
            "time_type": "exact",
            "outbound_exact_hour": 10, # 10:00 이전
            "inbound_exact_hour": 14  # 14:00 이후
        }
        start_time, end_time = get_time_range(exact_config, 'outbound')
        self.assertEqual(start_time, time(hour=0, minute=0))
        self.assertEqual(end_time, time(hour=10, minute=0))
        
        start_time, end_time = get_time_range(exact_config, 'inbound')
        self.assertEqual(start_time, time(hour=14, minute=0))
        self.assertEqual(end_time, time(hour=23, minute=59))

    async def helper_test_message_manager_update(self, existing_message_text=None, new_text="New Text", should_edit_fail=False, should_reply_fail=False):
        """MessageManager 업데이트 로직 헬퍼"""
        user_id = self.test_user_id
        mock_message = MagicMock()
        mock_message.message_id = 123
        mock_message.chat_id = user_id

        if existing_message_text:
            mock_message.text = existing_message_text
            self.message_manager.set_status_message(user_id, mock_message)

        async def mock_edit_text(*args, **kwargs):
            if should_edit_fail:
                raise MagicMock(side_effect=Exception("Edit failed")) # 일반적인 에러 상황
            if kwargs.get('text') == mock_message.text and existing_message_text is not None: # 메시지 내용 동일
                 # 실제 라이브러리는 "message is not modified" 에러 발생
                 # 여기서는 간단히 기존 메시지 객체 반환
                return mock_message 
            mock_message.text = kwargs.get('text') # 수정된 내용 반영
            return mock_message

        async def mock_reply_text(*args, **kwargs):
            if should_reply_fail:
                raise Exception("Reply failed")
            new_msg = MagicMock()
            new_msg.text = kwargs.get('text')
            return new_msg

        mock_message.edit_text = MagicMock(side_effect=mock_edit_text)
        mock_message.reply_text = MagicMock(side_effect=mock_reply_text)
        
        # update_status_message는 내부적으로 safe_edit_message를 호출함
        # safe_edit_message가 직접 Message 객체의 edit_text나 reply_text를 사용하므로
        # 해당 메소드들을 모킹
        with patch('flight_checker.safe_edit_message', new_callable=MagicMock) as mock_safe_edit:
            # safe_edit_message의 반환값을 설정
            if existing_message_text: # 기존 메시지가 있는 경우
                if should_edit_fail: # 편집 실패 시
                    if should_reply_fail: # 새 메시지 발송도 실패하는 경우
                        mock_safe_edit.return_value = None
                    else: # 새 메시지 발송 성공
                        new_reply_message = MagicMock(text=new_text)
                        mock_safe_edit.return_value = new_reply_message
                else: # 편집 성공
                    edited_message = MagicMock(text=new_text)
                    mock_safe_edit.return_value = edited_message
            else: # 기존 메시지가 없는 경우 (update_status_message는 이 경우 None을 반환해야 함)
                 mock_safe_edit.return_value = None


            updated_message = await self.message_manager.update_status_message(user_id, new_text)

            if existing_message_text:
                mock_safe_edit.assert_called_once() # safe_edit_message가 호출되었는지 확인
                call_args = mock_safe_edit.call_args[0]
                self.assertEqual(call_args[1], new_text) # 전달된 텍스트 확인

                if should_edit_fail and not should_reply_fail:
                    self.assertEqual(updated_message.text, new_text)
                    self.assertEqual(self.message_manager.status_messages[user_id].text, new_text)
                elif not should_edit_fail:
                    self.assertEqual(updated_message.text, new_text)
                    self.assertEqual(self.message_manager.status_messages[user_id].text, new_text)
                else: # 편집 및 새 메시지 모두 실패
                    self.assertIsNone(updated_message)
                    # 편집 실패 시 기존 메시지 삭제 로직 확인
                    self.assertNotIn(user_id, self.message_manager.status_messages)
            else: # 기존 메시지 없는 경우
                self.assertIsNone(updated_message) # 아무것도 하지 않아야 함
                mock_safe_edit.assert_not_called() # safe_edit_message 호출 안됨

    def test_message_manager_update_existing_success(self):
        """MessageManager 상태 메시지 업데이트 (기존 메시지 편집 성공)"""
        asyncio.run(self.helper_test_message_manager_update(existing_message_text="Old Text"))

    def test_message_manager_update_existing_edit_fail_reply_success(self):
        """MessageManager 상태 메시지 업데이트 (편집 실패, 새 메시지 성공)"""
        asyncio.run(self.helper_test_message_manager_update(existing_message_text="Old Text", should_edit_fail=True))

    def test_message_manager_update_existing_edit_fail_reply_fail(self):
        """MessageManager 상태 메시지 업데이트 (편집 실패, 새 메시지 실패)"""
        asyncio.run(self.helper_test_message_manager_update(existing_message_text="Old Text", should_edit_fail=True, should_reply_fail=True))

    def test_message_manager_update_no_existing_message(self):
        """MessageManager 상태 메시지 업데이트 (기존 메시지 없음)"""
        asyncio.run(self.helper_test_message_manager_update(new_text="New Text"))

    def test_message_manager_set_and_clear(self):
        """MessageManager 상태 메시지 등록 및 제거 테스트"""
        user_id = self.test_user_id
        mock_message = MagicMock()
        
        self.message_manager.set_status_message(user_id, mock_message)
        self.assertIn(user_id, self.message_manager.status_messages)
        self.assertEqual(self.message_manager.status_messages[user_id], mock_message)
        
        self.message_manager.clear_status_message(user_id)
        self.assertNotIn(user_id, self.message_manager.status_messages)


if __name__ == "__main__":
    unittest.main() 