export function useAuth() {
  const accessToken = localStorage.getItem('access_token');
  const username = localStorage.getItem('username');
  return { isAuthenticated: accessToken !== null, username };
}
