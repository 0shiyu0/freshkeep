/** 文件上传（食材图片 / 包装识别）。 */
import { request } from './http'

export interface FileAsset {
  id: string
  url: string
  mime_type: string
  size_bytes: number
  checksum: string
  created_at: string | null
}

export const fileApi = {
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<FileAsset>({
      url: '/files/upload',
      method: 'POST',
      data: form,
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
}
