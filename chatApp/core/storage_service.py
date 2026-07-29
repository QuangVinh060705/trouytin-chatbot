"""Storage abstraction: S3-compatible (AWS S3, Cloudflare R2, MinIO) or local disk."""

import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO

from core import config
from core.exceptions import StorageUploadError

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # boto3 chỉ cần khi STORAGE_PROVIDER=s3
    boto3 = None
    BotoCoreError = ClientError = Exception


class StorageService(ABC):
    @abstractmethod
    def upload_file(self, file: BinaryIO, object_key: str, content_type: str) -> str | None: ...

    @abstractmethod
    def delete_file(self, object_key: str) -> None: ...

    @abstractmethod
    def get_file(self, object_key: str, destination: Path) -> Path: ...

    @abstractmethod
    def generate_download_url(self, object_key: str) -> str: ...


class S3StorageService(StorageService):
    def __init__(self):
        if boto3 is None:
            raise StorageUploadError("Thư viện boto3 chưa được cài đặt.")
        if not all((config.S3_ACCESS_KEY, config.S3_SECRET_KEY, config.S3_BUCKET_NAME)):
            raise StorageUploadError("Cấu hình S3/R2 chưa đầy đủ.")
        self.bucket = config.S3_BUCKET_NAME
        self.client = boto3.client(
            "s3",
            endpoint_url=config.S3_ENDPOINT_URL,
            aws_access_key_id=config.S3_ACCESS_KEY,
            aws_secret_access_key=config.S3_SECRET_KEY,
            region_name=config.S3_REGION,
        )

    def upload_file(self, file: BinaryIO, object_key: str, content_type: str) -> str | None:
        try:
            file.seek(0)
            self.client.upload_fileobj(
                file, self.bucket, object_key,
                ExtraArgs={"ContentType": content_type},
            )
            return (
                f"{config.S3_PUBLIC_BASE_URL}/{object_key}"
                if config.S3_PUBLIC_BASE_URL else None
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            raise StorageUploadError("Không thể upload file lên cloud storage.") from exc

    def delete_file(self, object_key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=object_key)
        except (BotoCoreError, ClientError) as exc:
            raise StorageUploadError("Không thể xóa file trên cloud storage.") from exc

    def get_file(self, object_key: str, destination: Path) -> Path:
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            self.client.download_file(self.bucket, object_key, str(destination))
            return destination
        except (BotoCoreError, ClientError, OSError) as exc:
            raise StorageUploadError("Không thể tải file từ cloud storage.") from exc

    def generate_download_url(self, object_key: str) -> str:
        if config.S3_PUBLIC_BASE_URL:
            return f"{config.S3_PUBLIC_BASE_URL}/{object_key}"
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": object_key},
                ExpiresIn=config.PRESIGNED_URL_EXPIRES_SECONDS,
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageUploadError("Không thể tạo URL tải file.") from exc


class LocalStorageService(StorageService):
    """Fallback lưu file trên đĩa cục bộ khi chưa cấu hình S3/R2 (dev hoặc on-prem).

    Object key được giữ nguyên làm đường dẫn tương đối dưới LOCAL_STORAGE_DIR,
    nên round-trip upload -> get_file hoạt động giống hệt S3StorageService.
    """

    def __init__(self):
        self.root = Path(config.LOCAL_STORAGE_DIR)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, object_key: str) -> Path:
        return self.root / object_key

    def upload_file(self, file: BinaryIO, object_key: str, content_type: str) -> str | None:
        try:
            destination = self._path_for(object_key)
            destination.parent.mkdir(parents=True, exist_ok=True)
            file.seek(0)
            with open(destination, "wb") as out:
                shutil.copyfileobj(file, out)
            return None
        except OSError as exc:
            raise StorageUploadError("Không thể lưu file vào local storage.") from exc

    def delete_file(self, object_key: str) -> None:
        self._path_for(object_key).unlink(missing_ok=True)

    def get_file(self, object_key: str, destination: Path) -> Path:
        source = self._path_for(object_key)
        if not source.exists():
            raise StorageUploadError(f"Không tìm thấy file local: {object_key}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        return destination

    def generate_download_url(self, object_key: str) -> str:
        return f"local://{object_key}"


def get_storage_service() -> StorageService:
    provider = config.STORAGE_PROVIDER.lower()
    if provider == "local":
        return LocalStorageService()
    if provider != "s3":
        raise StorageUploadError(f"Storage provider chưa hỗ trợ: {config.STORAGE_PROVIDER}")
    if not all((config.S3_ACCESS_KEY, config.S3_SECRET_KEY, config.S3_BUCKET_NAME)):
        # STORAGE_PROVIDER=s3 nhưng thiếu credential -> rơi về local thay vì
        # chặn cứng toàn bộ luồng upload/ingest (giống cách Prop-Tech backend
        # tự fallback sang LocalStorageService khi R2 chưa cấu hình).
        return LocalStorageService()
    return S3StorageService()
