import apiClient from './client'

export const utilsApi = {
  /** Open the folder containing a file in the system file manager */
  openFolder(filePath: string) {
    return apiClient.post('/utils/open-folder', { file_path: filePath })
  },
}
