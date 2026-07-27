import { createContext, useContext, useEffect, useState } from 'react';

const PageTitleContext = createContext({
  title: '',
  subtitle: '',
  setPageTitle: () => {},
});

/** Provider — used once in UnifiedLayout */
export function PageTitleProvider({ children }) {
  const [title, setTitle] = useState('');
  const [subtitle, setSubtitle] = useState('');

  const setPageTitle = (t, s) => {
    setTitle(t || '');
    setSubtitle(s || '');
  };

  return (
    <PageTitleContext.Provider value={{ title, subtitle, setPageTitle }}>
      {children}
    </PageTitleContext.Provider>
  );
}

/** Hook — call from any page to push a title into the header */
export function usePageTitle(title, subtitle) {
  const ctx = useContext(PageTitleContext);
  useEffect(() => {
    ctx.setPageTitle(title, subtitle);
    return () => ctx.setPageTitle('', '');
  }, [title, subtitle]);
}

/** Read-only hook for the layout to consume */
export function usePageTitleValue() {
  const { title, subtitle } = useContext(PageTitleContext);
  return { title, subtitle };
}
